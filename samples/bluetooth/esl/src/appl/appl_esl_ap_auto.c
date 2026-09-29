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
#include <zephyr/sys/util.h>

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
static UINT16 synced_count;
static UINT16 target_count = CONFIG_ESL_AP_AUTO_SYNC_COUNT;
/* Retained across runs: a slot is committed only after successful sync. */
static UINT16 next_slot;
static UCHAR tag_pending = BT_ESL_FALSE;
static UCHAR tag_failed = BT_ESL_FALSE;
static UCHAR stop_requested = BT_ESL_FALSE;

/* Tag currently being walked through the connect->sync chain. The OTS
 * discovery-complete callback only hands back a BD address (it's a GATT
 * OTS callback, not an ESL AP one), so this is needed to recover the
 * esl_addr for the config call in appl_esl_ap_auto_on_ots_disc_complete(). */
static BT_ESL_ADDR current_esl_addr;
static BT_ESL_BD_ADDR current_peer_addr;
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
/* Only an explicitly failed connect/configure/sync attempt may be removed.
 * If removal fails, retain the flags and retry before allocating this slot. */
static API_RESULT appl_esl_ap_auto_cleanup_failed_tag(void)
{
    API_RESULT retval;

    if (BT_ESL_FALSE == tag_failed)
    {
        return BT_ESL_AP_SUCCESS;
    }

    retval = appl_esl_ap_remove_esl_tag(&current_esl_addr);
    if ((BT_ESL_AP_SUCCESS != retval) && (BT_ESL_AP_NOT_FOUND != retval))
    {
        APPL_ESL_ERR(
        "[APPL_AUTO]: Failed to remove failed tag [%d:%d] (0x%04X)\n",
        current_esl_addr.group_id, current_esl_addr.esl_id, retval);
        return retval;
    }

    tag_pending = BT_ESL_FALSE;
    tag_failed = BT_ESL_FALSE;
    APPL_ESL_TRC("[APPL_AUTO]: failed tag [%d:%d] removed; address available for retry\n",
                 current_esl_addr.group_id, current_esl_addr.esl_id);
    return BT_ESL_AP_SUCCESS;
}

static void appl_esl_ap_auto_fail(void)
{
    auto_state = AUTO_IDLE;
    (void)k_work_cancel_delayable(&rescan_work);
    (void)k_work_cancel_delayable(&sync_delay_work);
    tag_failed = tag_pending;
    (void)appl_esl_ap_auto_cleanup_failed_tag();
}

static UCHAR appl_esl_ap_auto_is_current(const BT_ESL_ADDR *esl_addr)
{
    return (BT_ESL_TRUE == tag_pending) &&
           (current_esl_addr.group_id == esl_addr->group_id) &&
           (current_esl_addr.esl_id == esl_addr->esl_id);
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
        appl_esl_ap_auto_fail();
    }
}

API_RESULT appl_esl_ap_auto_start(UINT16 count)
{
    API_RESULT retval;
    UINT16 capacity;

    if ((AUTO_IDLE != auto_state) && (AUTO_DONE != auto_state))
    {
        APPL_ESL_ERR(
        "[APPL_AUTO]: esl_ap auto rejected - automation already running (state %d)\n",
        auto_state);
        return BT_ESL_AP_BUSY;
    }

    count = (0U != count) ? count : (UINT16)CONFIG_ESL_AP_AUTO_SYNC_COUNT;
    capacity = MIN(APPL_ESL_MAX_NO_OF_GROUPS, APPL_ESL_AP_PAWR_SUBEVENT_COUNT) *
               APPL_ESL_AP_RESPONDERS_PER_GROUP;
    /* Allow a smaller single-group table for initialization diagnostics.
     * Multi-group allocation still uses a fixed stride of 16 ESL IDs. */
    if (1U == APPL_ESL_MAX_NO_OF_GROUPS)
    {
        capacity = MIN(capacity, APPL_ESL_MAX_NO_OF_TAGS_PER_GROUP);
    }
    if (((APPL_ESL_MAX_NO_OF_GROUPS > 1U) &&
         (APPL_ESL_MAX_NO_OF_TAGS_PER_GROUP < APPL_ESL_AP_RESPONDERS_PER_GROUP)) ||
        (count > APPL_ESL_AP_AUTO_MAX_COUNT) || (next_slot + count > capacity))
    {
        APPL_ESL_ERR(
        "[APPL_AUTO]: Cannot add %d tags (next slot %d, capacity %d); "
        "multi-group operation requires %d entries per group\n",
        count, next_slot, capacity, APPL_ESL_AP_RESPONDERS_PER_GROUP);
        return BT_ESL_AP_INVALID_PARAMETER;
    }

    retval = appl_esl_ap_auto_cleanup_failed_tag();
    if (BT_ESL_AP_SUCCESS != retval)
    {
        return retval;
    }

    auto_state = AUTO_SCANNING;
    synced_count = 0U;
    target_count = count;
    stop_requested = BT_ESL_FALSE;

    APPL_ESL_TRC(
    "[APPL_AUTO]: esl_ap auto requested (target %d tags, next [%d:%d]) - "\
    "init + scan\n",
    target_count, next_slot / APPL_ESL_AP_RESPONDERS_PER_GROUP,
    next_slot % APPL_ESL_AP_RESPONDERS_PER_GROUP);

    appl_init_esl();

    retval = appl_esl_ap_scan_esl_device(BT_ESL_TRUE);
    if (BT_ESL_AP_SUCCESS != retval)
    {
        APPL_ESL_ERR("[APPL_AUTO]: Failed to start scan (0x%04X)\n", retval);
        appl_esl_ap_auto_fail();
        return retval;
    }

    (void)k_work_reschedule(&rescan_work, APPL_ESL_AP_AUTO_RESCAN_INTERVAL);

    return BT_ESL_AP_SUCCESS;
}

void appl_esl_ap_auto_stop(void)
{
    stop_requested = BT_ESL_TRUE;
    (void)k_work_cancel_delayable(&rescan_work);

    if ((BT_ESL_TRUE == tag_pending) && (BT_ESL_FALSE == tag_failed))
    {
        /* Let the outstanding attempt reach a result; stopping is not a
         * sync failure and must not delete a tag or lose its callback. */
        APPL_ESL_TRC("[APPL_AUTO]: stop requested - finishing current tag\n");
        return;
    }

    auto_state = AUTO_IDLE;
    (void)k_work_cancel_delayable(&sync_delay_work);
    (void)appl_esl_ap_scan_esl_device(BT_ESL_FALSE);
    APPL_ESL_TRC("[APPL_AUTO]: esl_ap auto_stop - state reset to IDLE\n");
}

void appl_esl_ap_auto_on_connected(BT_ESL_ADDR *esl_addr, UCHAR status)
{
    API_RESULT retval;

    APPL_ESL_TRC(
    "[APPL_AUTO]: on_connected hook (tag [%d:%d], status %d, state %d)\n",
    esl_addr->group_id, esl_addr->esl_id, status, auto_state);

    if ((AUTO_CONNECTING != auto_state) ||
        (BT_ESL_FALSE == appl_esl_ap_auto_is_current(esl_addr)))
    {
        return;
    }

    if (0U != status)
    {
        APPL_ESL_ERR(
        "[APPL_AUTO]: ESL tag [%d:%d] connect failed (status %d)\n",
        esl_addr->group_id, esl_addr->esl_id, status);
        appl_esl_ap_auto_fail();
        return;
    }

    auto_state = AUTO_DISCOVERING;

    retval = appl_esl_ap_discover_esl_service(esl_addr);
    if (BT_ESL_AP_SUCCESS != retval)
    {
        APPL_ESL_ERR(
        "[APPL_AUTO]: Failed to discover ESL service for tag [%d:%d] (0x%04X)\n",
        esl_addr->group_id, esl_addr->esl_id, retval);
        appl_esl_ap_auto_fail();
    }
}

void appl_esl_ap_auto_on_disconnected(BT_ESL_ADDR *esl_addr)
{
    APPL_ESL_TRC(
    "[APPL_AUTO]: on_disconnected hook (tag [%d:%d], state %d)\n",
    esl_addr->group_id, esl_addr->esl_id, auto_state);

    /* During sync, the tag normally drops GATT before the sync callback.
     * An earlier disconnect aborts the attempt and must not leave stop
     * waiting for a discovery/configuration callback that cannot arrive. */
    if ((BT_ESL_TRUE == appl_esl_ap_auto_is_current(esl_addr)) &&
        ((AUTO_CONNECTING == auto_state) || (AUTO_DISCOVERING == auto_state) ||
         (AUTO_DISCOVERING_OTS == auto_state) || (AUTO_CONFIGURING == auto_state)))
    {
        APPL_ESL_ERR("[APPL_AUTO]: tag disconnected before sync\n");
        appl_esl_ap_auto_fail();
    }
}

void appl_esl_ap_auto_on_discovered(BT_ESL_ADDR esl_addr, UINT16 status)
{
    API_RESULT retval;

    APPL_ESL_TRC(
    "[APPL_AUTO]: on_discovered hook (tag [%d:%d], status %d, state %d)\n",
    esl_addr.group_id, esl_addr.esl_id, status, auto_state);

    if ((AUTO_DISCOVERING != auto_state) ||
        (BT_ESL_FALSE == appl_esl_ap_auto_is_current(&esl_addr)))
    {
        return;
    }

    if (BT_ESL_AP_SUCCESS != status)
    {
        APPL_ESL_ERR(
        "[APPL_AUTO]: ESL tag [%d:%d] service discovery failed (status %d)\n",
        esl_addr.group_id, esl_addr.esl_id, status);
        appl_esl_ap_auto_fail();
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
        appl_esl_ap_auto_fail();
    }
#else
    auto_state = AUTO_CONFIGURING;

    retval = appl_esl_ap_config(&esl_addr);
    if (BT_ESL_AP_SUCCESS != retval)
    {
        APPL_ESL_ERR(
        "[APPL_AUTO]: Failed to config tag [%d:%d] (0x%04X)\n",
        esl_addr.group_id, esl_addr.esl_id, retval);
        appl_esl_ap_auto_fail();
    }
#endif /* APPL_ESL_AP_OTS_SUPPORT */
}

void appl_esl_ap_auto_on_configured(BT_ESL_ADDR *esl_addr, UCHAR error, UINT16 result)
{
    API_RESULT retval;

    APPL_ESL_TRC(
    "[APPL_AUTO]: on_configured hook (tag [%d:%d], error %d, result %d, state %d)\n",
    esl_addr->group_id, esl_addr->esl_id, error, result, auto_state);

    if ((AUTO_CONFIGURING != auto_state) ||
        (BT_ESL_FALSE == appl_esl_ap_auto_is_current(esl_addr)))
    {
        return;
    }

    if ((0U != error) || (BT_ESL_AP_SUCCESS != result))
    {
        APPL_ESL_ERR(
        "[APPL_AUTO]: ESL tag [%d:%d] config failed (error %d, result %d)\n",
        esl_addr->group_id, esl_addr->esl_id, error, result);
        appl_esl_ap_auto_fail();
        return;
    }

    if (BT_ESL_FALSE == padv_started)
    {
        retval = appl_esl_ap_start_periodic_adv();
        if (BT_ESL_AP_SUCCESS != retval)
        {
            APPL_ESL_ERR(
            "[APPL_AUTO]: Failed to start periodic adv (0x%04X)\n", retval);
            appl_esl_ap_auto_fail();
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
        appl_esl_ap_auto_fail();
    }
}

void appl_esl_ap_auto_on_synchronised(BT_ESL_ADDR *esl_addr, UINT16 status)
{
    API_RESULT retval;

    APPL_ESL_TRC(
    "[APPL_AUTO]: on_synchronised hook (tag [%d:%d], status 0x%04X, state %d)\n",
    esl_addr->group_id, esl_addr->esl_id, status, auto_state);

    if ((AUTO_SYNCING != auto_state) ||
        (BT_ESL_FALSE == appl_esl_ap_auto_is_current(esl_addr)))
    {
        return;
    }

    if (BT_ESL_AP_SUCCESS != status)
    {
        APPL_ESL_ERR(
        "[APPL_AUTO]: ESL tag [%d:%d] sync failed (status 0x%04X)\n",
        esl_addr->group_id, esl_addr->esl_id, status);
        appl_esl_ap_auto_fail();
        return;
    }

    tag_pending = BT_ESL_FALSE;
    next_slot++;
    synced_count++;

    APPL_ESL_TRC(
    "[APPL_AUTO]: %d/%d tags synced\n",
    synced_count, target_count);

    if ((BT_ESL_TRUE == stop_requested) || (synced_count >= target_count))
    {
        APPL_ESL_TRC("[APPL_AUTO]: batch finished - synced tags retained\n");
        auto_state = AUTO_DONE;
        return;
    }

    retval = appl_esl_ap_disconnect_esl(esl_addr);
    if ((BT_ESL_AP_SUCCESS != retval) && (BT_ESL_AP_INVALID_STATE != retval))
    {
        APPL_ESL_ERR(
        "[APPL_AUTO]: Failed to disconnect tag [%d:%d] (0x%04X)\n",
        esl_addr->group_id, esl_addr->esl_id, retval);
        appl_esl_ap_auto_fail();
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
        appl_esl_ap_auto_fail();
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

    auto_state = AUTO_ADDING;
    (void)k_work_cancel_delayable(&rescan_work);

    (void)appl_esl_ap_scan_esl_device(BT_ESL_FALSE);

    esl_addr.group_id = (UCHAR)(next_slot / APPL_ESL_AP_RESPONDERS_PER_GROUP);
    esl_addr.esl_id = (UCHAR)(next_slot % APPL_ESL_AP_RESPONDERS_PER_GROUP);

    current_esl_addr = esl_addr;
    current_peer_addr = *peer_addr;

    retval = appl_esl_ap_add_esl_tag(&esl_addr, peer_addr);
    if (BT_ESL_AP_SUCCESS != retval)
    {
        APPL_ESL_ERR(
        "[APPL_AUTO]: Failed to add ESL tag [%d:%d] (0x%04X)\n",
        esl_addr.group_id, esl_addr.esl_id, retval);
        appl_esl_ap_auto_fail();
        return;
    }

    tag_pending = BT_ESL_TRUE;

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
        appl_esl_ap_auto_fail();
    }
}

#ifdef APPL_ESL_AP_OTS_SUPPORT
void appl_esl_ap_auto_on_ots_disc_complete(BT_ESL_BD_ADDR *bd_addr, UINT16 result)
{
    API_RESULT retval;

    APPL_ESL_TRC(
    "[APPL_AUTO]: on_ots_disc_complete hook (result %d, state %d)\n",
    result, auto_state);

    if ((AUTO_DISCOVERING_OTS != auto_state) ||
        (BT_ESL_FALSE == tag_pending) ||
        (BT_ESL_FALSE == BT_ESL_COMPARE_BD_ADDR_AND_TYPE(&current_peer_addr, bd_addr)))
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
        appl_esl_ap_auto_fail();
    }
}
#endif /* APPL_ESL_AP_OTS_SUPPORT */

#endif /* CONFIG_ESL_AP_AUTOMATION */
