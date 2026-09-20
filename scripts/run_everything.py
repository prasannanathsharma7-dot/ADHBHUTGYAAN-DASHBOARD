"""
Runs the ENTIRE pipeline in order, unattended, with automatic retry on
failure -- so you don't have to run each step by hand.

    1. scraper/discovery.py         find new outlier + search videos
    2. run_local_pipeline.py        scrape their comments (--skip-enrich)
    3. nlp/prefilter.py             free junk filter
    4. enrichment                   Claude Batch or Ollama (see --enrich-with)
    5. scraper/transcripts.py       fetch what the videos actually said
    6. nlp/run_gap_analysis.py      score unanswered questions

Each step retries up to 3 times (with a growing pause) if it exits
with an error. A step that still fails after 3 tries does NOT stop the
whole run -- later steps that can still make progress on whatever is
already in the database go ahead anyway, and the final summary says
exactly which step(s) failed so nothing is silently lost.

Every run's full output is saved to logs/run_TIMESTAMP.log as well as
printed live, so you can check what happened even if you weren't
watching.

Usage:
    python scripts\\run_everything.py
        # one full pass through all 6 steps, then exit

    python scripts\\run_everything.py --repeat-every-hours 6
        # one full pass, then sleep 6 hours, then again -- forever,
        # until you close the window or press Ctrl+C

    python scripts\\run_everything.py --enrich-with ollama
        # force the free local model instead of auto-detecting
"""
import argparse
import os
import subprocess
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import time
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(REPO_ROOT, "logs")

MAX_RETRIES = 3
RETRY_DELAY_SEC = [30, 90, 180]  # grows with each attempt


def log(logfile, message: str):
    print(message)
    logfile.write(message + "\n")
    logfile.flush()


def run_step(logfile, name: str, cmd: list) -> bool:
    """Runs one step, retrying on non-zero exit. Returns True on
    eventual success, False if it never succeeded."""
    for attempt in range(1, MAX_RETRIES + 1):
        log(logfile, f"\n{'=' * 70}\n{name}  (attempt {attempt}/{MAX_RETRIES})\n{'=' * 70}")
        process = subprocess.Popen(
            cmd, cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        for line in process.stdout:
            log(logfile, line.rstrip())
        process.wait()

        if process.returncode == 0:
            log(logfile, f"[OK] {name} finished successfully.")
            return True

        log(logfile, f"[FAILED] {name} exited with code {process.returncode}.")
        if attempt < MAX_RETRIES:
            delay = RETRY_DELAY_SEC[attempt - 1]
            log(logfile, f"Retrying in {delay}s...")
            time.sleep(delay)

    log(logfile, f"[GIVING UP] {name} failed after {MAX_RETRIES} attempts -- continuing with the next step anyway.")
    return False


def detect_enrichment(mode: str) -> str:
    if mode != "auto":
        return mode
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key and key != "sk-ant-...":
        return "claude"
    return "ollama"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeat-every-hours", type=float, default=0, help="0 = run once and exit (default)")
    parser.add_argument(
        "--enrich-with", choices=["auto", "claude", "ollama", "skip"], default="auto",
        help="auto = claude if ANTHROPIC_API_KEY looks real, else ollama",
    )
    parser.add_argument("--ollama-workers", type=int, default=4)
    parser.add_argument("--discovery-multiplier", type=float, default=2.5)
    args = parser.parse_args()

    os.makedirs(LOG_DIR, exist_ok=True)
    py = sys.executable  # the venv's own python, whatever launched this script

    cycle = 1
    while True:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        log_path = os.path.join(LOG_DIR, f"run_{timestamp}.log")
        with open(log_path, "w", encoding="utf-8") as logfile:
            log(logfile, f"Adhbhutgyaan pipeline -- cycle {cycle} -- started {timestamp}")
            log(logfile, f"Full log: {log_path}")

            results = {}
            results["discovery"] = run_step(
                logfile, "1/6 Discovery",
                [py, "scraper/discovery.py", "--multiplier", str(args.discovery_multiplier)],
            )
            results["scrape"] = run_step(
                logfile, "2/6 Scrape",
                [py, "scripts/run_local_pipeline.py", "--skip-enrich"],
            )
            results["prefilter"] = run_step(
                logfile, "3/6 Prefilter",
                [py, "nlp/prefilter.py"],
            )

            enrich_mode = detect_enrichment(args.enrich_with)
            if enrich_mode == "skip":
                log(logfile, "\n4/6 Enrichment -- skipped (--enrich-with skip)")
                results["enrich"] = True
            elif enrich_mode == "claude":
                results["enrich"] = run_step(logfile, "4/6 Enrichment (Claude Batch)", [py, "nlp/batch_pipeline.py"])
            else:
                results["enrich"] = run_step(
                    logfile, "4/6 Enrichment (Ollama, free)",
                    [py, "nlp/local_enrich_ollama.py", "--workers", str(args.ollama_workers)],
                )

            results["transcripts"] = run_step(logfile, "5/6 Transcripts", [py, "scraper/transcripts.py"])
            results["gap_analysis"] = run_step(logfile, "6/6 Gap analysis", [py, "nlp/run_gap_analysis.py"])

            log(logfile, f"\n{'=' * 70}\nCycle {cycle} summary\n{'=' * 70}")
            for step, ok in results.items():
                log(logfile, f"  {step}: {'OK' if ok else 'FAILED (see above)'}")

        if args.repeat_every_hours <= 0:
            print(f"\nDone. Full log saved to {log_path}")
            break

        print(f"\nSleeping {args.repeat_every_hours}h before the next cycle. Press Ctrl+C to stop.")
        try:
            time.sleep(args.repeat_every_hours * 3600)
        except KeyboardInterrupt:
            print("\nStopped.")
            break
        cycle += 1


if __name__ == "__main__":
    main()
