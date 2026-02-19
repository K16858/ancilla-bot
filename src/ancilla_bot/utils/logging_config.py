"""
ログ設定
"""

import sys

from loguru import logger

DEFAULT_FORMAT = "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}"


def init_logging(
    *,
    level: str = "INFO",
    log_file: str | None = None,
) -> None:
    """
    loguru のロガーを初期化する。

    Args:
        level: ログレベル（DEBUG / INFO / WARNING / ERROR）
        log_file: ログファイルのパス。指定時はファイルにも出力する
    """
    logger.remove()
    logger.add(
        sys.stderr,
        format=DEFAULT_FORMAT,
        level=level,
    )
    if log_file:
        logger.add(
            log_file,
            format=DEFAULT_FORMAT,
            level=level,
            rotation="1 day",
            retention="7 days",
        )
