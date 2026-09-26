# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20.0)
find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})

project(bt_esl_tag)

# ESL root
set(ESL_ROOT ..)

# ESL SRC
set(ESL_SRC ${ESL_ROOT}/src)

if(KERNEL_VERSION_MAJOR GREATER_EQUAL 4)
    target_compile_definitions(app PRIVATE
    -DZEPHYR_4_0_0_OR_LATER)
endif()

if(CONFIG_BT_ESL_OTS)
  target_compile_definitions(app PRIVATE
      -DAPPL_ESL_TAG_OTS_SUPPORT)
endif()

include_directories(
  ${ESL_SRC}/appl
  ${ESL_SRC}/pal
)

target_sources(app PRIVATE
  ${ESL_SRC}/appl/appl_esl_tag.c
  ${ESL_SRC}/appl/appl_main.c
  ${ESL_SRC}/appl/cli_esl_tag.c
  ${ESL_SRC}/bal/BT_esl_pl.c
  ${ESL_SRC}/pal/esl_io.c
)

if(CONFIG_ESL_TAG_LOG)
  target_sources(app PRIVATE
    ${ESL_SRC}/appl/appl_esl_tag_log.c
  )
endif()

# Split the CRC-patched ELF into separate app and CCFG binaries.
# zephyr_final is defined in a child scope (Zephyr adds itself via
# add_subdirectory), so add_custom_command(TARGET) is not allowed here.
# add_custom_target with DEPENDS runs after zephyr_final and all its
# POST_BUILD steps (including crc_tool) have completed.
add_custom_target(split_binary ALL
  DEPENDS zephyr_final
  COMMAND ${CMAKE_OBJCOPY}
          --remove-section=.ti_ccfg
          --gap-fill 0xff
          -O binary
          ${CMAKE_BINARY_DIR}/zephyr/${KERNEL_ELF_NAME}
          ${CMAKE_BINARY_DIR}/zephyr/app.bin
  COMMAND ${CMAKE_OBJCOPY}
          --only-section=.ti_ccfg
          -O binary
          ${CMAKE_BINARY_DIR}/zephyr/${KERNEL_ELF_NAME}
          ${CMAKE_BINARY_DIR}/zephyr/ccfg.bin
)