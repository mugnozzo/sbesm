import io

from sbesm.logging_setup import configure_logging


def test_verbose_shows_debug():
    buf = io.StringIO()
    logger = configure_logging(verbose=True, stream=buf)
    logger.debug("dbg")
    logger.info("inf")
    output = buf.getvalue()
    assert "dbg" in output
    assert "inf" in output


def test_quiet_suppresses_info():
    buf = io.StringIO()
    logger = configure_logging(quiet=True, stream=buf)
    logger.info("inf")
    logger.warning("warn")
    output = buf.getvalue()
    assert "inf" not in output
    assert "warn" in output


def test_default_shows_info_not_debug():
    buf = io.StringIO()
    logger = configure_logging(stream=buf)
    logger.debug("dbg")
    logger.info("inf")
    output = buf.getvalue()
    assert "dbg" not in output
    assert "inf" in output


if __name__ == "__main__":
    test_verbose_shows_debug()
    test_quiet_suppresses_info()
    test_default_shows_info_not_debug()
    print("ok")
