/**
 *  \file appl_esl_tag_log.c
 *
 *  In-RAM debug log of pings and images received by the ESL Tag: tracks the
 *  total ping count, the time of the last ping, and the last image
 *  received. Contents are lost on reset or power-cycle, there is no
 *  flash/NVS persistence.
 */

/*
 *  Copyright (C) 2025. LTIMindtree Ltd.
 *  All rights reserved.
 */

/* --------------------------------------------- Header File Inclusion */
#include "appl_esl_tag_log.h"

#ifdef CONFIG_ESL_TAG_LOG

/* --------------------------------------------- Static Global Variables */
static UINT32 appl_esl_log_ping_count;
static UINT32 appl_esl_log_last_ping_time;   /* valid iff ping_count > 0 */
static UCHAR  appl_esl_log_last_image_index;
static UCHAR  appl_esl_log_has_image;        /* image_index 0 is valid, need explicit flag */

/* --------------------------------------------- Functions */
void appl_esl_log_init(void)
{
    appl_esl_log_ping_count = 0U;
    appl_esl_log_last_ping_time = 0U;
    appl_esl_log_last_image_index = 0U;
    appl_esl_log_has_image = BT_ESL_FALSE;
}

void appl_esl_log_ping(void)
{
    appl_esl_log_ping_count++;
    appl_esl_log_last_ping_time = BT_esl_get_current_time_pl();
}

void appl_esl_log_image_received(UCHAR image_index)
{
    appl_esl_log_last_image_index = image_index;
    appl_esl_log_has_image = BT_ESL_TRUE;
}

void appl_esl_log_dump_all(void)
{
    APPL_ESL_INF("Number of Pings: %d\n", appl_esl_log_ping_count);

    if (0U == appl_esl_log_ping_count)
    {
        APPL_ESL_INF("Time since last ping: never\n");
    }
    else
    {
        APPL_ESL_INF("Time since last ping: %ds\n",
            (BT_esl_get_current_time_pl() - appl_esl_log_last_ping_time) / 1000U);
    }

    if (BT_ESL_FALSE == appl_esl_log_has_image)
    {
        APPL_ESL_INF("Latest Image Received: none\n");
    }
    else
    {
        APPL_ESL_INF("Latest Image Received: %d\n", appl_esl_log_last_image_index);
    }
}

#endif /* CONFIG_ESL_TAG_LOG */
