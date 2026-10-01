"""Builders for ``esl_ap`` shell command strings.

Keep every command string the GUI sends in this module so that the mapping
to ``SHELL_CMD`` entries in ``src/appl/cli_esl_ap.c`` lives in one place.
"""

AUTO_MAX_COUNT = 1000  # APPL_ESL_AP_AUTO_MAX_COUNT in appl_esl_ap_auto.h
GROUP_ID_MAX = 0x7F    # ESL group IDs are 7 bits
ESL_ID_MAX = 0xFE      # 0xFF is the broadcast ESL ID


def auto(count: int) -> str:
    """Sync ``count`` additional tags (cmd_ap_auto, decimal argument)."""
    if not 1 <= count <= AUTO_MAX_COUNT:
        raise ValueError(f"count must be 1-{AUTO_MAX_COUNT}")
    return f"esl_ap auto {count}"


def auto_stop() -> str:
    """Stop automation after the in-flight tag finishes (cmd_ap_auto_stop)."""
    return "esl_ap auto_stop"


def ping(group: int, esl: int) -> str:
    """Ping one tag (cmd_eslp_ping_command).

    The firmware parses both IDs with ``strtol(..., 16)`` while every log
    line prints them in decimal, so convert to hex here.
    """
    if not 0 <= group <= GROUP_ID_MAX:
        raise ValueError(f"group must be 0-{GROUP_ID_MAX}")
    if not 0 <= esl <= ESL_ID_MAX:
        raise ValueError(f"esl must be 0-{ESL_ID_MAX}")
    return f"esl_ap ping {group:x} {esl:x}"
