# Demo script (under 3 minutes)

Everything below runs **offline from the repository** (`--cache-mode replay` or
`--offline`): no API key, no credits, no network. Record in a terminal with a
large font, plus a browser window for the report.

Setup before recording:

```bash
git clone https://github.com/soujasK/slopwatch && cd slopwatch
python -m venv .venv && . .venv/Scripts/activate   # macOS/Linux: . .venv/bin/activate
pip install -e .
```

## 0:00 - 0:20  An agent cites a page full of slop signals

```bash
slopwatch filter --serp-json examples/serp_cibil.json --offline --annotate | head -60
```

Say: "Agents answer from the top search results. Here is Google India for *how to
improve cibil score fast*. The top two results are dictionary definitions of the
word 'improve'. Number 3 is a US government research program called IMPROVE.
SlopWatch annotates each result: no named author, and it covers a quarter of the
question's words, so it lands in the low band." (`examples/serp_dolo650.json`
also works; under rubric v4 its anonymous Q&A page is *mixed*, just under the
low threshold.)

## 0:20 - 0:50  "Agents trust the top results. We measured them."

```bash
slopwatch report --cache-mode replay
```

Open `report/observatory.html`. Say: "100 SerpApi searches across Google, DuckDuckGo
and Yahoo India and Google US. The headline: X% of scored India results show
low-quality signals, with a 95% interval, coverage, and best/worst-case bounds."

## 0:50 - 1:30  Observatory walkthrough

Scroll: by engine (Google vs DuckDuckGo and Yahoo), by category, India vs US, by rank.
Point at "What the low-quality results have in common": in Indian results the
signal is anonymity, off-query pages and sellers' own content, **not** classic
affiliate spam.

## 1:30 - 1:55  Validation box

Say: "Labels from two blind LLMs (no human labels). Our first two rubrics failed
their held-out tests, and we report that. The third was fitted on development
data only and tested once on 30 brand-new queries: precision P, recall R. It is
conservative: it almost never drops a good page, and it misses most bad ones."

## 1:55 - 2:30  One line of code; the agent's sources change

```python
from slopwatch.filter.serpapi_tools import web_search   # instead of serpapi_search_tools
tools = [web_search()]                                    # any of 14 agent frameworks
```

```bash
slopwatch demo --cache-mode replay
```

Say: "Same agent, same pre-registered questions, raw vs filtered top 5. For CIBIL
the filter drops the off-topic NIH page, and the agent says honestly, both times,
that its sources do not answer the question: Google's top 5 simply has nothing on
CIBIL. For the other seven nothing is dropped. All 8 are in DEMO_RESULTS.md; the
filter's effect is on what the agent reads, shown live next."

Live, for any question (1 credit per new search; cached repeats are free):

```bash
slopwatch serve          # opens http://127.0.0.1:8765
```

Type any question. Results appear at once,
each page is read and scored live, then the same agent answers twice side by side:
without SlopWatch and with it, every citation marked clear or slop.

## 2:30 - 2:45  Close

```bash
pip install "slopwatch[agents] @ git+https://github.com/soujasK/slopwatch"
```

"SlopWatch: don't feed your agent slop." Show the repo URL.

Replace X, P and R with the numbers in `report/numbers.json` before recording.
