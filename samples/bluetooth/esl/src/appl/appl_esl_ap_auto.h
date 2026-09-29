/**
 *  \file appl_esl_ap_auto.h
 *
 *  This Header File contains ESL AP Automation State Machine Declarations.
 */

/*
 *  Copyright (C) 2025. LTIMindtree Ltd.
 *  All rights reserved.
 */

#ifndef _H_APPL_ESL_AP_AUTO_
#define _H_APPL_ESL_AP_AUTO_

/* ----------------------------------------------- Header File Inclusion */
#include "appl_esl_ap.h"

#ifdef CONFIG_ESL_AP_AUTOMATION

#define APPL_ESL_AP_AUTO_MAX_COUNT 1000U

/* ----------------------------------------------- Structures/Data Types */
enum appl_esl_ap_auto_state
{
    AUTO_IDLE,
    AUTO_SCANNING,
    AUTO_ADDING,
    AUTO_CONNECTING,
    AUTO_DISCOVERING,
    AUTO_DISCOVERING_OTS,
    AUTO_CONFIGURING,
    AUTO_STARTING_PADV,
    AUTO_SYNCING,
    AUTO_DONE
};

/* -------------------------------------------- Function Declarations */
/* count: number of additional tags to sync before stopping, or 0 to use the
 * Kconfig default (CONFIG_ESL_AP_AUTO_SYNC_COUNT). Synced tags are retained
 * across runs, filling IDs 0-15 before advancing to the next group.
 * Returns BT_ESL_AP_INVALID_PARAMETER if the batch exceeds remaining capacity.
 * Returns BT_ESL_AP_BUSY if automation is already running (state is neither
 * AUTO_IDLE nor AUTO_DONE), without disturbing the run in progress. */
API_RESULT appl_esl_ap_auto_start(UINT16 count);
/* Finish any in-flight attempt, then stop. Only failed attempts are removed. */
void appl_esl_ap_auto_stop(void);

/* Hook callbacks, invoked from appl_esl_ap.c at the end of the matching
 * BT_ESL_AP_CALLBACKS handler. Signatures mirror those handlers exactly. */
void appl_esl_ap_auto_on_connected(BT_ESL_ADDR *esl_addr, UCHAR status);
void appl_esl_ap_auto_on_disconnected(BT_ESL_ADDR *esl_addr);
void appl_esl_ap_auto_on_discovered(BT_ESL_ADDR esl_addr, UINT16 status);
void appl_esl_ap_auto_on_configured(BT_ESL_ADDR *esl_addr, UCHAR error, UINT16 result);
void appl_esl_ap_auto_on_synchronised(BT_ESL_ADDR *esl_addr, UINT16 status);
void appl_esl_ap_auto_on_device_found(BT_ESL_BD_ADDR *peer_addr, UCHAR *adv_data, UINT16 adv_length);
#ifdef APPL_ESL_AP_OTS_SUPPORT
void appl_esl_ap_auto_on_ots_disc_complete(BT_ESL_BD_ADDR *bd_addr, UINT16 result);
#endif /* APPL_ESL_AP_OTS_SUPPORT */

#endif /* CONFIG_ESL_AP_AUTOMATION */

#endif /* _H_APPL_ESL_AP_AUTO_ */
