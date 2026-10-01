# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20.0)
find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})

project(bt_esl_ap)

# The prebuilt esl_core.a sizes its PAwR command buffer (sync_buffer) for a
# single group, so group 1+ overruns it. Link a copy with that symbol weakened;
# appl_esl_ap.c defines a sync_buffer sized for CONFIG_BT_ESL_MAX_GROUPS_SUPPORTED.
if(TARGET esl_core)
  get_target_property(ESL_CORE_LIB esl_core IMPORTED_LOCATION)
  set(ESL_CORE_PATCHED_LIB ${CMAKE_CURRENT_BINARY_DIR}/esl_core_patched.a)
  execute_process(
    COMMAND ${CMAKE_OBJCOPY} --weaken-symbol=sync_buffer
            ${ESL_CORE_LIB} ${ESL_CORE_PATCHED_LIB}
    RESULT_VARIABLE ESL_CORE_PATCH_RESULT)
  if(NOT ESL_CORE_PATCH_RESULT EQUAL 0)
    message(FATAL_ERROR "Failed to patch ${ESL_CORE_LIB}")
  endif()
  set_target_properties(esl_core PROPERTIES IMPORTED_LOCATION ${ESL_CORE_PATCHED_LIB})
  set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS ${ESL_CORE_LIB})
endif()

# ESL root
set(ESL_ROOT ..)

# ESL SRC
set(ESL_SRC ${ESL_ROOT}/src)

if(KERNEL_VERSION_MAJOR GREATER_EQUAL 4)
    target_compile_definitions(app PRIVATE
    -DZEPHYR_4_0_0_OR_LATER
    -DBT_ESL_AP_HAVE_SUBEVENT_ADJUSTMENT)
endif()

target_compile_definitions(app PRIVATE
    -DAPPL_ESL_DO_NOT_USE_DEFAULT_CONN_PARAMS)

if(CONFIG_BT_OTS_CLIENT)
  target_compile_definitions(app PRIVATE
      -DAPPL_ESL_AP_OTS_SUPPORT)
endif()

include_directories(
  ${ESL_SRC}/appl
  ${ESL_SRC}/pal
)

target_sources(app PRIVATE
  ${ESL_SRC}/appl/appl_esl_ap.c
  ${ESL_SRC}/appl/appl_main.c
  ${ESL_SRC}/appl/cli_esl_ap.c
  ${ESL_SRC}/bal/BT_esl_pl.c
  ${ESL_SRC}/pal/esl_io.c
)

if(CONFIG_ESL_AP_AUTOMATION)
  target_sources(app PRIVATE
    ${ESL_SRC}/appl/appl_esl_ap_auto.c)
endif()

if(CONFIG_ESL_AP_LOG)
  target_sources(app PRIVATE
    ${ESL_SRC}/appl/appl_esl_ap_log.c)
endif()
