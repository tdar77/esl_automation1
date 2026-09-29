/**
 *  \file appl_esl_ap_log.c
 */

/*
 *  Copyright (C) 2025. LTIMindtree Ltd.
 *  All rights reserved.
 */

/* --------------------------------------------- Header File Inclusion */
#include "appl_esl_ap_log.h"

#ifdef CONFIG_ESL_AP_LOG

/* --------------------------------------------- Structures/Data Types */
typedef struct
{
    UCHAR  in_use;
    UCHAR  group_id;
    UCHAR  esl_id;
    UINT32 ping_count;
    UINT32 last_ping_time;
    UCHAR  last_image_index;
    UCHAR  has_image;
} APPL_ESL_AP_LOG_ENTRY;

/* --------------------------------------------- Static Global Variables */
#define APPL_ESL_AP_LOG_CAPACITY \
    (APPL_ESL_MAX_NO_OF_GROUPS * APPL_ESL_MAX_NO_OF_TAGS_PER_GROUP)
static APPL_ESL_AP_LOG_ENTRY appl_esl_ap_log_table[APPL_ESL_AP_LOG_CAPACITY];

/* --------------------------------------------- Function Prototype */
static APPL_ESL_AP_LOG_ENTRY *appl_esl_ap_log_find_or_alloc(BT_ESL_ADDR *esl_addr);

/* --------------------------------------------- Functions */
void appl_esl_ap_log_init(void)
{
    BT_ESL_mem_set(appl_esl_ap_log_table, 0x00, sizeof(appl_esl_ap_log_table));
}

static APPL_ESL_AP_LOG_ENTRY *appl_esl_ap_log_find_or_alloc(BT_ESL_ADDR *esl_addr)
{
    UINT16 i;
    UINT16 free_index;
    UCHAR have_free_index;

    free_index = 0U;
    have_free_index = BT_ESL_FALSE;

    for (i = 0U; i < APPL_ESL_AP_LOG_CAPACITY; i++)
    {
        if (BT_ESL_TRUE == appl_esl_ap_log_table[i].in_use)
        {
            if ((appl_esl_ap_log_table[i].group_id == esl_addr->group_id) &&
                (appl_esl_ap_log_table[i].esl_id == esl_addr->esl_id))
            {
                return &appl_esl_ap_log_table[i];
            }
        }
        else if (BT_ESL_FALSE == have_free_index)
        {
            free_index = i;
            have_free_index = BT_ESL_TRUE;
        }
    }

    if (BT_ESL_FALSE == have_free_index)
    {
        APPL_ESL_ERR("[APPL]: AP log table full, dropping update for tag [%d:%d]\n",
            esl_addr->group_id, esl_addr->esl_id);
        return NULL;
    }

    appl_esl_ap_log_table[free_index].in_use = BT_ESL_TRUE;
    appl_esl_ap_log_table[free_index].group_id = esl_addr->group_id;
    appl_esl_ap_log_table[free_index].esl_id = esl_addr->esl_id;

    return &appl_esl_ap_log_table[free_index];
}

void appl_esl_ap_log_ping(BT_ESL_ADDR *esl_addr)
{
    APPL_ESL_AP_LOG_ENTRY *entry;

    entry = appl_esl_ap_log_find_or_alloc(esl_addr);
    if (NULL != entry)
    {
        entry->ping_count++;
        entry->last_ping_time = BT_esl_get_current_time_pl();
    }
}

void appl_esl_ap_log_image_sent(BT_ESL_ADDR *esl_addr, UCHAR image_index)
{
    APPL_ESL_AP_LOG_ENTRY *entry;

    entry = appl_esl_ap_log_find_or_alloc(esl_addr);
    if (NULL != entry)
    {
        entry->last_image_index = image_index;
        entry->has_image = BT_ESL_TRUE;
    }
}

void appl_esl_ap_log_dump_all(void)
{
    UINT16 i;

    for (i = 0U; i < APPL_ESL_AP_LOG_CAPACITY; i++)
    {
        if (BT_ESL_TRUE == appl_esl_ap_log_table[i].in_use)
        {
            APPL_ESL_INF("Tag [%d:%d]\n",
                appl_esl_ap_log_table[i].group_id, appl_esl_ap_log_table[i].esl_id);
            APPL_ESL_INF("  Number of Pings: %d\n", appl_esl_ap_log_table[i].ping_count);

            if (0U == appl_esl_ap_log_table[i].ping_count)
            {
                APPL_ESL_INF("  Time since last ping: never\n");
            }
            else
            {
                APPL_ESL_INF("  Time since last ping: %ds\n",
                    (BT_esl_get_current_time_pl() - appl_esl_ap_log_table[i].last_ping_time) / 1000U);
            }

            if (BT_ESL_FALSE == appl_esl_ap_log_table[i].has_image)
            {
                APPL_ESL_INF("  Latest Image Sent: none\n");
            }
            else
            {
                APPL_ESL_INF("  Latest Image Sent: %d\n", appl_esl_ap_log_table[i].last_image_index);
            }
        }
    }
}

#endif /* CONFIG_ESL_AP_LOG */
