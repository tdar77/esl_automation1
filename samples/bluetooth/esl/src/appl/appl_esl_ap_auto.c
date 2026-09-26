/**
 *  \file appl_esl_ap_auto.c
 *
 */

/*
 *  Copyright (C) 2025. LTIMindtree Ltd.
 *  All rights reserved.
 */

/* --------------------------------------------- Header File Inclusion */
#include "appl_esl_ap_auto.h"

#ifdef CONFIG_ESL_AP_AUTOMATION

#include <zephyr/kernel.h>

/* --------------------------------------------- Macros */
/* Retry interval for the AUTO_SCANNING toggle: the controller sometimes
 * fails to (re)report an in-range tag until the scan session is toggled, so
 * we periodically stop/restart the scan until a tag is found. */
#define APPL_ESL_AP_AUTO_RESCAN_INTERVAL K_SECONDS(4)

/* Delay between starting periodic adv (PAwR) and issuing the first sync
 * request. The manual CLI flow has an incidental delay here (a human types
 * "start_padv" then "sync_esl" as separate commands); automation collapses
 * that to zero, which was observed to cause a BT_ESL_AP_TIMEOUT (0x0101) on
 * the first tag's sync - the controller needs a moment after the periodic
 * adv HCI commands complete before it's actually broadcasting. Only needed
 * once per session, for the tag that triggers the initial padv start. */
#define APPL_ESL_AP_AUTO_SYNC_DELAY K_SECONDS(1)

/* --------------------------------------------- Static Global Variables */
static enum appl_esl_ap_auto_state auto_state = AUTO_IDLE;
static UCHAR synced_count;
static UCHAR target_count = CONFIG_ESL_AP_AUTO_SYNC_COUNT;
/* Number of tags that have been added to the tag table in the current (or
 * most recent) run.  This may be greater than synced_count when automation
 * is stopped mid-flight (a tag was added but not yet synced).  Used by
 * appl_esl_ap_auto_cleanup_tags() to remove exactly the right entries
 * before a subsequent run re-uses the same slot indices. */
static UCHAR added_count;

/* Tag currently being walked through the connect->sync chain. The OTS
 * discovery-complete callback only hands back a BD address (it's a GATT
 * OTS callback, not an ESL AP one), so this is needed to recover the
 * esl_addr for the config call in appl_esl_ap_auto_on_ots_disc_complete(). */
static BT_ESL_ADDR current_esl_addr;
/* Guards against restarting periodic adv on every tag in B10's loop - it
 * only needs to be started once for the whole session. */
static UCHAR padv_started = BT_ESL_FALSE;
/* Tag to sync once APPL_ESL_AP_AUTO_SYNC_DELAY elapses after the initial
 * periodic adv start (see sync_delay_work_handler). */
static BT_ESL_ADDR sync_pending_addr;

static void rescan_work_handler(struct k_work *work);
static K_WORK_DELAYABLE_DEFINE(rescan_work, rescan_work_handler);

static void sync_delay_work_handler(struct k_work *work);
static K_WORK_DELAYABLE_DEFINE(sync_delay_work, sync_delay_work_handler);

/* --------------------------------------------- Functions */
/**
 * Remove all tag-table entries that were added during the most recent auto
 * run.  Automation always uses group 0 and assigns esl_id sequentially from
 * 0, so the affected slots are [0][0] … [0][added_count-1].  Slots that
 * were successfully synced (< synced_count) are in SYNCHRONIZED state;
 * slots that were only partially set up may be in any other state.
 * BT_esl_ap_remove_esl_tag() handles both.  Any error is traced but does
 * not abort the loop — we want to clean up as many slots as possible.
 */
static void appl_esl_ap_auto_cleanup_tags(void)
{
    UCHAR        i;
    BT_ESL_ADDR  addr;
    API_RESULT   retval;

    if (0U == added_count)
    {
        return;
    }

    APPL_ESL_TRC(
    "[APPL_AUTO]: cleanup - removing %d tag(s) from table\n", added_count);

    addr.group_id = 0U;
    for (i = 0U; i < added_count; i++)
    {
        addr.esl_id = i;
        retval = appl_esl_ap_remove_esl_tag(&addr);
        if (BT_ESL_AP_SUCCESS != retval)
        {
            APPL_ESL_TRC(
            "[APPL_AUTO]: cleanup - remove tag [0:%d] retval 0x%04X (ignored)\n",
            i, retval);
        }
    }

    added_count = 0U;
}


static void rescan_work_handler(struct k_work *work)
{
    BT_ESL_IGNORE_UNUSED_PARAM(work);

    if (AUTO_SCANNING != auto_state)
    {
        return;
    }

    APPL_ESL_TRC("[APPL_AUTO]: rescan retry - toggling scan\n");

    (void)appl_esl_ap_scan_esl_device(BT_ESL_FALSE);
    (void)appl_esl_ap_scan_esl_device(BT_ESL_TRUE);

    (void)k_work_reschedule(&rescan_work, APPL_ESL_AP_AUTO_RESCAN_INTERVAL);
}

static void sync_delay_work_handler(struct k_work *work)
{
    API_RESULT retval;

    BT_ESL_IGNORE_UNUSED_PARAM(work);

    if (AUTO_SYNCING != auto_state)
    {
        return;
    }

    APPL_ESL_TRC(
    "[APPL_AUTO]: sync delay elapsed - syncing tag [%d:%d]\n",
    sync_pending_addr.group_id, sync_pending_addr.esl_id);

    retval = appl_esl_ap_sync_with_esl(&sync_pending_addr);
    if (BT_ESL_AP_SUCCESS != retval)
    {
        APPL_ESL_ERR(
        "[APPL_AUTO]: Failed to sync tag [%d:%d] (0x%04X)\n",
        sync_pending_addr.group_id, sync_pending_addr.esl_id, retval);
        auto_state = AUTO_IDLE;
    }
}

API_RESULT appl_esl_ap_auto_start(UCHAR count)
{
    API_RESULT retval;

    if ((AUTO_IDLE != auto_state) && (AUTO_DONE != auto_state))
    {
        APPL_ESL_ERR(
        "[APPL_AUTO]: esl_ap auto rejected - automation already running (state %d)\n",
        auto_state);
        return BT_ESL_AP_BUSY;
    }

    /* Remove any tag-table entries left over from the previous run so that
    * re-using the same [0][0…N-1] slot indices does not fail. */
    appl_esl_ap_auto_cleanup_tags();

    auto_state   = AUTO_SCANNING;
    synced_count = 0U;
    target_count = (0U != count) ? count : (UCHAR)CONFIG_ESL_AP_AUTO_SYNC_COUNT;

    APPL_ESL_TRC(
    "[APPL_AUTO]: esl_ap auto requested (target %d tags) - "\
    "init + scan\n",
    target_count);

    appl_init_esl();

    retval = appl_esl_ap_scan_esl_device(BT_ESL_TRUE);
    if (BT_ESL_AP_SUCCESS != retval)
    {
        APPL_ESL_ERR("[APPL_AUTO]: Failed to start scan (0x%04X)\n", retval);
        auto_state = AUTO_IDLE;
        return retval;
    }

    (void)k_work_reschedule(&rescan_work, APPL_ESL_AP_AUTO_RESCAN_INTERVAL);

    return BT_ESL_AP_SUCCESS;
}

void appl_esl_ap_auto_stop(void)
{
    auto_state = AUTO_IDLE;

    (void)k_work_cancel_delayable(&rescan_work);
    (void)k_work_cancel_delayable(&sync_delay_work);

    /* Remove any tag-table entries left over from the previous run so that
     * re-using the same [0][0…N-1] slot indices does not fail. */
    appl_esl_ap_auto_cleanup_tags();

    APPL_ESL_TRC("[APPL_AUTO]: esl_ap auto_stop - state reset to IDLE\n");
}

void appl_esl_ap_auto_on_connected(BT_ESL_ADDR *esl_addr, UCHAR status)
{
    API_RESULT retval;

    APPL_ESL_TRC(
    "[APPL_AUTO]: on_connected hook (tag [%d:%d], status %d, state %d)\n",
    esl_addr->group_id, esl_addr->esl_id, status, auto_state);

    if (AUTO_CONNECTING != auto_state)
    {
        return;
    }

    if (0U != status)
    {
        APPL_ESL_ERR(
        "[APPL_AUTO]: ESL tag [%d:%d] connect failed (status %d)\n",
        esl_addr->group_id, esl_addr->esl_id, status);
        auto_state = AUTO_IDLE;
        return;
    }

    auto_state = AUTO_DISCOVERING;

    retval = appl_esl_ap_discover_esl_service(esl_addr);
    if (BT_ESL_AP_SUCCESS != retval)
    {
        APPL_ESL_ERR(
        "[APPL_AUTO]: Failed to discover ESL service for tag [%d:%d] (0x%04X)\n",
        esl_addr->group_id, esl_addr->esl_id, retval);
        auto_state = AUTO_IDLE;
    }
}

void appl_esl_ap_auto_on_disconnected(BT_ESL_ADDR *esl_addr)
{
    APPL_ESL_TRC(
    "[APPL_AUTO]: on_disconnected hook (tag [%d:%d], state %d)\n",
    esl_addr->group_id, esl_addr->esl_id, auto_state);
}

void appl_esl_ap_auto_on_discovered(BT_ESL_ADDR esl_addr, UINT16 status)
{
    API_RESULT retval;

    APPL_ESL_TRC(
    "[APPL_AUTO]: on_discovered hook (tag [%d:%d], status %d, state %d)\n",
    esl_addr.group_id, esl_addr.esl_id, status, auto_state);

    if (AUTO_DISCOVERING != auto_state)
    {
        return;
    }

    if (BT_ESL_AP_SUCCESS != status)
    {
        APPL_ESL_ERR(
        "[APPL_AUTO]: ESL tag [%d:%d] service discovery failed (status %d)\n",
        esl_addr.group_id, esl_addr.esl_id, status);
        auto_state = AUTO_IDLE;
        return;
    }

#ifdef APPL_ESL_AP_OTS_SUPPORT
    auto_state = AUTO_DISCOVERING_OTS;

    retval = appl_esl_ap_discover_ots(&esl_addr);
    if (BT_ESL_AP_SUCCESS != retval)
    {
        APPL_ESL_ERR(
        "[APPL_AUTO]: Failed to discover OTS for tag [%d:%d] (0x%04X)\n",
        esl_addr.group_id, esl_addr.esl_id, retval);
        auto_state = AUTO_IDLE;
    }
#else
    auto_state = AUTO_CONFIGURING;

    retval = appl_esl_ap_config(&esl_addr);
    if (BT_ESL_AP_SUCCESS != retval)
    {
        APPL_ESL_ERR(
        "[APPL_AUTO]: Failed to config tag [%d:%d] (0x%04X)\n",
        esl_addr.group_id, esl_addr.esl_id, retval);
        auto_state = AUTO_IDLE;
    }
#endif /* APPL_ESL_AP_OTS_SUPPORT */
}

void appl_esl_ap_auto_on_configured(BT_ESL_ADDR *esl_addr, UCHAR error, UINT16 result)
{
    API_RESULT retval;

    APPL_ESL_TRC(
    "[APPL_AUTO]: on_configured hook (tag [%d:%d], error %d, result %d, state %d)\n",
    esl_addr->group_id, esl_addr->esl_id, error, result, auto_state);

    if (AUTO_CONFIGURING != auto_state)
    {
        return;
    }

    if ((0U != error) || (BT_ESL_AP_SUCCESS != result))
    {
        APPL_ESL_ERR(
        "[APPL_AUTO]: ESL tag [%d:%d] config failed (error %d, result %d)\n",
        esl_addr->group_id, esl_addr->esl_id, error, result);
        auto_state = AUTO_IDLE;
        return;
    }

    if (BT_ESL_FALSE == padv_started)
    {
        retval = appl_esl_ap_start_periodic_adv();
        if (BT_ESL_AP_SUCCESS != retval)
        {
            APPL_ESL_ERR(
            "[APPL_AUTO]: Failed to start periodic adv (0x%04X)\n", retval);
            auto_state = AUTO_IDLE;
            return;
        }
        padv_started = BT_ESL_TRUE;

        auto_state = AUTO_SYNCING;
        sync_pending_addr = *esl_addr;
        (void)k_work_reschedule(&sync_delay_work, APPL_ESL_AP_AUTO_SYNC_DELAY);
        return;
    }

    auto_state = AUTO_SYNCING;

    retval = appl_esl_ap_sync_with_esl(esl_addr);
    if (BT_ESL_AP_SUCCESS != retval)
    {
        APPL_ESL_ERR(
        "[APPL_AUTO]: Failed to sync tag [%d:%d] (0x%04X)\n",
        esl_addr->group_id, esl_addr->esl_id, retval);
        auto_state = AUTO_IDLE;
    }
}

void appl_esl_ap_auto_on_synchronised(BT_ESL_ADDR *esl_addr, UINT16 status)
{
    API_RESULT retval;

    APPL_ESL_TRC(
    "[APPL_AUTO]: on_synchronised hook (tag [%d:%d], status 0x%04X, state %d)\n",
    esl_addr->group_id, esl_addr->esl_id, status, auto_state);

    if (AUTO_SYNCING != auto_state)
    {
        return;
    }

    if (BT_ESL_AP_SUCCESS != status)
    {
        APPL_ESL_ERR(
        "[APPL_AUTO]: ESL tag [%d:%d] sync failed (status 0x%04X)\n",
        esl_addr->group_id, esl_addr->esl_id, status);
        auto_state = AUTO_IDLE;
        return;
    }

    synced_count++;

    APPL_ESL_TRC(
    "[APPL_AUTO]: %d/%d tags synced\n",
    synced_count, target_count);

    if (synced_count >= target_count)
    {
        APPL_ESL_TRC("[APPL_AUTO]: target reached - all tags synced\n");
        auto_state = AUTO_DONE;
        return;
    }

    retval = appl_esl_ap_disconnect_esl(esl_addr);
    if ((BT_ESL_AP_SUCCESS != retval) && (BT_ESL_AP_INVALID_STATE != retval))
    {
        APPL_ESL_ERR(
        "[APPL_AUTO]: Failed to disconnect tag [%d:%d] (0x%04X)\n",
        esl_addr->group_id, esl_addr->esl_id, retval);
        auto_state = AUTO_IDLE;
        return;
    }
    else if (BT_ESL_AP_INVALID_STATE == retval)
    {
        /* Tag already disconnected its ACL on its own once PAwR sync took
         * over - observed on hardware, the on_disconnected hook fires before
         * on_synchronised does. Not an error, just nothing left to do. */
        APPL_ESL_TRC(
        "[APPL_AUTO]: tag [%d:%d] already disconnected, continuing\n",
        esl_addr->group_id, esl_addr->esl_id);
    }

    auto_state = AUTO_SCANNING;

    retval = appl_esl_ap_scan_esl_device(BT_ESL_TRUE);
    if (BT_ESL_AP_SUCCESS != retval)
    {
        APPL_ESL_ERR("[APPL_AUTO]: Failed to restart scan (0x%04X)\n", retval);
        auto_state = AUTO_IDLE;
        return;
    }

    (void)k_work_reschedule(&rescan_work, APPL_ESL_AP_AUTO_RESCAN_INTERVAL);
}

void appl_esl_ap_auto_on_device_found(BT_ESL_BD_ADDR *peer_addr, UCHAR *adv_data, UINT16 adv_length)
{
    BT_ESL_ADDR esl_addr;
    API_RESULT  retval;

    BT_ESL_IGNORE_UNUSED_PARAM(adv_data);

    APPL_ESL_TRC(
    "[APPL_AUTO]: on_device_found hook (adv_length %d, state %d)\n",
    adv_length, auto_state);

    if (AUTO_SCANNING != auto_state)
    {
        return;
    }

    (void)k_work_cancel_delayable(&rescan_work);

    (void)appl_esl_ap_scan_esl_device(BT_ESL_FALSE);

    esl_addr.group_id = 0U;
    esl_addr.esl_id   = synced_count;

    current_esl_addr = esl_addr;

    retval = appl_esl_ap_add_esl_tag(&esl_addr, peer_addr);
    if (BT_ESL_AP_SUCCESS != retval)
    {
        APPL_ESL_ERR(
        "[APPL_AUTO]: Failed to add ESL tag [%d:%d] (0x%04X)\n",
        esl_addr.group_id, esl_addr.esl_id, retval);
        auto_state = AUTO_IDLE;
        return;
    }

    /* Track how many slots were populated so cleanup removes exactly
     * the right entries on the next auto run or manual stop. */
    added_count++;

    APPL_ESL_TRC(
    "[APPL_AUTO]: ESL tag [%d:%d] added, connecting\n",
    esl_addr.group_id, esl_addr.esl_id);

    auto_state = AUTO_CONNECTING;

    retval = appl_esl_ap_connect_esl(&esl_addr);
    if (BT_ESL_AP_SUCCESS != retval)
    {
        APPL_ESL_ERR(
        "[APPL_AUTO]: Failed to connect ESL tag [%d:%d] (0x%04X)\n",
        esl_addr.group_id, esl_addr.esl_id, retval);
        auto_state = AUTO_IDLE;
    }
}

#ifdef APPL_ESL_AP_OTS_SUPPORT
void appl_esl_ap_auto_on_ots_disc_complete(BT_ESL_BD_ADDR *bd_addr, UINT16 result)
{
    API_RESULT retval;

    BT_ESL_IGNORE_UNUSED_PARAM(bd_addr);

    APPL_ESL_TRC(
    "[APPL_AUTO]: on_ots_disc_complete hook (result %d, state %d)\n",
    result, auto_state);

    if (AUTO_DISCOVERING_OTS != auto_state)
    {
        return;
    }

    /* appl_esl_ap_ots_disc_complete() already handled the OTS config on
     * success internally; continue unconditionally into ESL config either
     * way, per plan. */
    auto_state = AUTO_CONFIGURING;

    retval = appl_esl_ap_config(&current_esl_addr);
    if (BT_ESL_AP_SUCCESS != retval)
    {
        APPL_ESL_ERR(
        "[APPL_AUTO]: Failed to config tag [%d:%d] (0x%04X)\n",
        current_esl_addr.group_id, current_esl_addr.esl_id, retval);
        auto_state = AUTO_IDLE;
    }
}
#endif /* APPL_ESL_AP_OTS_SUPPORT */

#endif /* CONFIG_ESL_AP_AUTOMATION */
