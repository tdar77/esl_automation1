/**
 *  \file appl_esl_tag_log.h
 *
 *  This Header File declares the in-RAM debug log of pings and images
 *  received by the ESL Tag.
 */

/*
 *  Copyright (C) 2025. LTIMindtree Ltd.
 *  All rights reserved.
 */

#ifndef _H_APPL_ESL_TAG_LOG_
#define _H_APPL_ESL_TAG_LOG_

/* ----------------------------------------------- Header File Inclusion */
#include "appl_main.h"

/* ----------------------------------------------- Function Declarations */

#ifdef CONFIG_ESL_TAG_LOG

/**
 *  Note: this log is backed by static RAM only. Its contents are lost on
 *  reset or power-cycle - there is no flash/NVS persistence. Only the ping
 *  count, the time of the last ping, and the last image received are
 *  tracked.
 */

void appl_esl_log_init(void);
void appl_esl_log_ping(void);
void appl_esl_log_image_received(UCHAR image_index);
void appl_esl_log_dump_all(void);

#else  /* CONFIG_ESL_TAG_LOG */

static inline void appl_esl_log_init(void)
{
}

static inline void appl_esl_log_ping(void)
{
}

static inline void appl_esl_log_image_received(UCHAR image_index)
{
    ARG_UNUSED(image_index);
}

static inline void appl_esl_log_dump_all(void)
{
}

#endif /* CONFIG_ESL_TAG_LOG */

#endif /* _H_APPL_ESL_TAG_LOG_ */
