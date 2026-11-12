import os

os.environ.setdefault("INVESTSYNC_HISTORY", "0")  # tests never write data/history
os.environ.setdefault("PEER_MODE", "auto")  # tests never call the AI peer step (it would hit DeepSeek)
os.environ.setdefault("RESEARCH", "0")
os.environ.setdefault("SEC_FACTS", "0")  # no SEC XBRL download in tests
os.environ.setdefault("BRIEF", "0")  # the analyst brief has its own test
os.environ.setdefault("FORECAST", "0")  # the forecast step has its own tests (test_forecast.py)  # nor the research desk (network + DeepSeek)
