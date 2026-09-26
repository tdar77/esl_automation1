/**
 *  \file appl_esl_ap_log.h
 *
 *  This Header File contains Application Layer Declarations for Zephyr.
 */

/*
 *  Copyright (C) 2025. LTIMindtree Ltd.
 *  All rights reserved.
 */

#ifndef _H_APPL_ESL_AP_LOG_
#define _H_APPL_ESL_AP_LOG_

/* ----------------------------------------------- Header File Inclusion */
#include "appl_esl_ap.h"

/* ----------------------------------------------- Function Declarations */

#ifdef CONFIG_ESL_AP_LOG
void appl_esl_ap_log_init(void);
void appl_esl_ap_log_ping(BT_ESL_ADDR *esl_addr);
void appl_esl_ap_log_image_sent(BT_ESL_ADDR *esl_addr, UCHAR image_index);
void appl_esl_ap_log_dump_all(void);
#else  /* CONFIG_ESL_AP_LOG */
static inline void appl_esl_ap_log_init(void) {}
static inline void appl_esl_ap_log_ping(BT_ESL_ADDR *esl_addr) { ARG_UNUSED(esl_addr); }
static inline void appl_esl_ap_log_image_sent(BT_ESL_ADDR *esl_addr, UCHAR image_index)
{
    ARG_UNUSED(esl_addr);
    ARG_UNUSED(image_index);
}
static inline void appl_esl_ap_log_dump_all(void) {}
#endif /* CONFIG_ESL_AP_LOG */

#endif /* _H_APPL_ESL_AP_LOG_ */
