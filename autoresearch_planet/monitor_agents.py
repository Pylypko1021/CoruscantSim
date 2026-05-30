from __future__ import annotations

import argparse
import csv
import curses
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class ResultSnapshot:
    total_runs: int
    best_score: float | None
    last_score: float | None
    last_timestamp: str | None
    last_row: dict[str, str] | None
    recent_rows: list[dict[str, str]]
    score_series: list[float]
    recent_events: list[str]
    last_mtime: float | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Interactive monitor for Coruscant autoresearch agents.")
    parser.add_argument(
        "--results",
        default=str(Path(__file__).with_name("results.tsv")),
        help="Path to results.tsv",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Refresh interval in seconds",
    )
    parser.add_argument(
        "--recent",
        type=int,
        default=12,
        help="How many recent runs to show",
    )
    parser.add_argument(
        "--process-filter",
        default="coruscant|autoresearch|train.py|copilot",
        help="Regex passed to pgrep -f for active process list",
    )
    parser.add_argument(
        "--target-iters",
        type=int,
        default=30,
        help="Expected optimization iterations for progress bar.",
    )
    parser.add_argument(
        "--plain",
        action="store_true",
        help="Print one plain-text snapshot (useful for non-interactive shells).",
    )
    return parser.parse_args()


def read_results(path: Path, recent_count: int) -> ResultSnapshot:
    if not path.exists():
        return ResultSnapshot(
            total_runs=0,
            best_score=None,
            last_score=None,
            last_timestamp=None,
            last_row=None,
            recent_rows=[],
            score_series=[],
            recent_events=[],
            last_mtime=None,
        )

    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            rows.append(row)

    best_score: float | None = None
    last_score: float | None = None
    last_timestamp: str | None = None
    last_row: dict[str, str] | None = rows[-1] if rows else None

    scores: list[float] = []
    events: list[str] = []
    rolling_best: float | None = None

    for idx, row in enumerate(rows):
        ts = row.get("timestamp", "n/a")
        score_str = row.get("score", "")
        try:
            score = float(score_str)
        except ValueError:
            events.append(f"SKIP   {ts}  invalid score")
            continue

        scores.append(score)
        if best_score is None or score < best_score:
            best_score = score

        if idx == 0 or rolling_best is None:
            rolling_best = score
            events.append(f"START  {ts}  s={score:.6f}")
        elif score < rolling_best:
            rolling_best = score
            events.append(f"KEEP   {ts}  s={score:.6f} (new best)")
        else:
            events.append(f"REVERT {ts}  s={score:.6f} (+{score - rolling_best:.6f})")

    if last_row is not None:
        try:
            last_score = float(last_row.get("score", ""))
        except ValueError:
            last_score = None
        last_timestamp = last_row.get("timestamp")

    return ResultSnapshot(
        total_runs=len(rows),
        best_score=best_score,
        last_score=last_score,
        last_timestamp=last_timestamp,
        last_row=last_row,
        recent_rows=rows[-recent_count:],
        score_series=scores,
        recent_events=events[-max(10, recent_count):],
        last_mtime=path.stat().st_mtime,
    )


def active_processes(pattern: str) -> list[str]:
    cmd = ["pgrep", "-fal", pattern]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True)
    except subprocess.CalledProcessError:
        return []
    return [ln.strip() for ln in out.splitlines() if ln.strip()][:14]


def fmt_age(seconds: float | None) -> str:
    if seconds is None:
        return "n/a"
    if seconds < 1:
        return "just now"
    if seconds < 60:
        return f"{seconds:.1f}s ago"
    minutes = seconds / 60.0
    if minutes < 60:
        return f"{minutes:.1f}m ago"
    hours = minutes / 60.0
    return f"{hours:.1f}h ago"


def status_line(snapshot: ResultSnapshot) -> str:
    if snapshot.last_score is None or snapshot.best_score is None:
        return "No score yet"
    delta = snapshot.last_score - snapshot.best_score
    if abs(delta) < 1e-12:
        return "Last run is currently BEST"
    if delta > 0:
        return f"Last run is +{delta:.6f} above best"
    return f"Last run improved best by {abs(delta):.6f}"


def _safe_addstr(win: curses.window, y: int, x: int, text: str, attr: int = 0) -> None:
    h, w = win.getmaxyx()
    if y < 0 or y >= h or x >= w:
        return
    max_len = max(0, w - x - 1)
    if max_len <= 0:
        return
    try:
        win.addstr(y, x, text[:max_len], attr)
    except curses.error:
        return


def _render_panel_border(win: curses.window, title: str, color: int) -> None:
    win.erase()
    win.box()
    _safe_addstr(win, 0, 2, f" {title} ", color | curses.A_BOLD)


def _metric_line(label: str, value: str, width: int) -> str:
    left = f"{label}:"
    gap = max(1, width - len(left) - len(value) - 2)
    return f"{left}{' ' * gap}{value}"


def _ascii_sparkline(values: list[float], width: int) -> str:
    if width <= 0:
        return ""
    if not values:
        return "." * width
    levels = " .:-=+*#%@"

    if len(values) > width:
        step = len(values) / float(width)
        sampled = [values[int(i * step)] for i in range(width)]
    else:
        sampled = values[:]
        if len(sampled) < width:
            sampled = [sampled[0]] * (width - len(sampled)) + sampled

    vmin = min(sampled)
    vmax = max(sampled)
    if abs(vmax - vmin) < 1e-12:
        return levels[len(levels) // 2] * width

    out: list[str] = []
    for val in sampled:
        ratio = (val - vmin) / (vmax - vmin)
        idx = int(round(ratio * (len(levels) - 1)))
        idx = max(0, min(len(levels) - 1, idx))
        out.append(levels[idx])
    return "".join(out)


def _format_recent_row(row: dict[str, str]) -> str:
    return "{ts} | s={s} | g={g} a={a} c={c} m={m}".format(
        ts=row.get("timestamp", "n/a"),
        s=row.get("score", "n/a"),
        g=row.get("greenhouse_forcing_w_m2", "n/a"),
        a=row.get("surface_albedo", "n/a"),
        c=row.get("cloud_cooling_coeff", "n/a"),
        m=row.get("atmosphere_mass_kg", "n/a"),
    )


def _render_header(
    win: curses.window,
    refresh_interval: float,
    paused: bool,
    stale: bool,
    total_runs: int,
    target_iters: int,
    active_train: bool,
    last_score: float | None,
    filter_label: str,
) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    title_attr = curses.color_pair(1) | curses.A_BOLD
    state_attr = curses.color_pair(3 if paused else 2) | curses.A_BOLD
    stale_attr = curses.color_pair(4 if stale else 2) | curses.A_BOLD
    run_attr = curses.color_pair(2 if active_train else 3) | curses.A_BOLD

    safe_target = max(1, target_iters)
    ratio = max(0.0, min(1.0, total_runs / float(safe_target)))
    bar_w = 18
    fill = int(round(bar_w * ratio))
    bar = "[" + ("#" * fill) + ("-" * (bar_w - fill)) + "]"
    score_str = f"{last_score:.6f}" if last_score is not None else "n/a"

    _safe_addstr(win, 0, 2, " Coruscant Agents Monitor ", title_attr)
    _safe_addstr(win, 0, 32, f"Now: {now}", curses.color_pair(6))

    _safe_addstr(win, 1, 2, f"Progress: {bar} {total_runs}/{safe_target}", curses.color_pair(6))
    _safe_addstr(win, 1, 36, f"Current: {'train.py running' if active_train else 'idle'}", run_attr)
    _safe_addstr(win, 1, 70, f"Last: {score_str}", curses.color_pair(6))

    _safe_addstr(win, 2, 2, f"Refresh: {'paused' if paused else f'{refresh_interval:.1f}s'}", state_attr)
    _safe_addstr(win, 2, 28, "q quit", curses.color_pair(6))
    _safe_addstr(win, 2, 36, "p pause", curses.color_pair(6))
    _safe_addstr(win, 2, 46, "+/- speed", curses.color_pair(6))
    _safe_addstr(win, 2, 58, "j/k scroll", curses.color_pair(6))
    _safe_addstr(win, 2, 70, "tab focus", curses.color_pair(6))

    _safe_addstr(win, 3, 2, "Status:", curses.color_pair(6))
    _safe_addstr(win, 3, 10, "stale" if stale else "live", stale_attr)
    _safe_addstr(win, 3, 22, f"filter: {filter_label} (f cycle)", curses.color_pair(5))


def _render_summary_panel(win: curses.window, snapshot: ResultSnapshot) -> None:
    _render_panel_border(win, "Autoresearch", curses.color_pair(1))
    inner_w = max(10, win.getmaxyx()[1] - 4)

    mtime_age = None
    if snapshot.last_mtime is not None:
        mtime_age = time.time() - snapshot.last_mtime

    lines = [
        _metric_line("Total runs", str(snapshot.total_runs), inner_w),
        _metric_line("Best score", f"{snapshot.best_score:.9f}" if snapshot.best_score is not None else "n/a", inner_w),
        _metric_line("Last score", f"{snapshot.last_score:.9f}" if snapshot.last_score is not None else "n/a", inner_w),
        _metric_line("Updated", fmt_age(mtime_age), inner_w),
        _metric_line("Last ts", snapshot.last_timestamp or "n/a", inner_w),
        "",
        status_line(snapshot),
        "",
        "Score trend:",
        _ascii_sparkline(snapshot.score_series[-120:], max(10, inner_w - 2)),
        "",
    ]

    last = snapshot.last_row or {}
    lines.extend(
        [
            "Last params:",
            f"g={last.get('greenhouse_forcing_w_m2', 'n/a')}  a={last.get('surface_albedo', 'n/a')}",
            f"c={last.get('cloud_cooling_coeff', 'n/a')}  m={last.get('atmosphere_mass_kg', 'n/a')}",
        ]
    )

    for idx, text in enumerate(lines, start=1):
        if idx >= win.getmaxyx()[0] - 1:
            break
        attr = curses.color_pair(6)
        if "BEST" in text or "improved" in text:
            attr = curses.color_pair(2) | curses.A_BOLD
        if "above best" in text:
            attr = curses.color_pair(5)
        _safe_addstr(win, idx, 2, text, attr)


def _render_scrolling_panel(
    win: curses.window,
    title: str,
    rows: list[str],
    offset: int,
    color: int,
) -> int:
    _render_panel_border(win, title, color)
    h, _ = win.getmaxyx()
    body_h = max(1, h - 2)
    max_offset = max(0, len(rows) - body_h)
    offset = min(offset, max_offset)
    visible = rows[offset : offset + body_h]

    for idx, text in enumerate(visible, start=1):
        _safe_addstr(win, idx, 2, text, curses.color_pair(6))

    if max_offset > 0:
        hint = f"{offset + 1}-{offset + len(visible)} / {len(rows)}"
        _safe_addstr(win, h - 1, 2, hint, curses.color_pair(5))
    return offset


def _init_colors() -> None:
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_CYAN, -1)
    curses.init_pair(2, curses.COLOR_GREEN, -1)
    curses.init_pair(3, curses.COLOR_YELLOW, -1)
    curses.init_pair(4, curses.COLOR_RED, -1)
    curses.init_pair(5, curses.COLOR_MAGENTA, -1)
    curses.init_pair(6, curses.COLOR_WHITE, -1)


def _plain_snapshot(results_path: Path, recent: int, process_filter: str) -> int:
    snapshot = read_results(results_path, recent)
    proc_lines = active_processes(process_filter)
    mtime_age = None
    if snapshot.last_mtime is not None:
        mtime_age = time.time() - snapshot.last_mtime

    print("Coruscant Agents Monitor")
    print(f"Total runs: {snapshot.total_runs}")
    print(f"Best score: {snapshot.best_score}")
    print(f"Last score: {snapshot.last_score}")
    print(f"Updated: {fmt_age(mtime_age)}")
    print(f"Status: {status_line(snapshot)}")
    print("Processes:")
    for line in proc_lines:
        print(f"- {line}")
    print("Recent:")
    for row in snapshot.recent_rows:
        print(f"- {_format_recent_row(row)}")
    print("Events:")
    for event in snapshot.recent_events:
        print(f"- {event}")
    return 0


def run_monitor(results_path: Path, interval: float, recent: int, process_filter: str, target_iters: int) -> int:
    def _loop(stdscr: curses.window) -> int:
        _init_colors()
        curses.curs_set(0)
        stdscr.nodelay(True)
        stdscr.timeout(100)

        refresh_interval = interval
        paused = False
        proc_offset = 0
        row_offset = 0
        evt_offset = 0
        focus = "rows"
        next_refresh_at = 0.0

        filter_presets = [
            ("all", process_filter),
            ("train", "train.py|monitor_agents.py"),
            ("copilot", "copilot|copilot-chat|tsserver"),
        ]
        filter_index = 0
        active_filter_label, active_filter_pattern = filter_presets[filter_index]

        snapshot = read_results(results_path, recent)
        proc_lines = active_processes(active_filter_pattern)

        while True:
            now_ts = time.time()
            if not paused and now_ts >= next_refresh_at:
                snapshot = read_results(results_path, recent)
                proc_lines = active_processes(active_filter_pattern)
                next_refresh_at = now_ts + refresh_interval

            stdscr.erase()
            h, w = stdscr.getmaxyx()
            if h < 16 or w < 90:
                _safe_addstr(stdscr, 1, 2, "Terminal too small. Resize to at least 90x16.", curses.color_pair(4) | curses.A_BOLD)
                _safe_addstr(stdscr, 3, 2, "Press q to quit.", curses.color_pair(6))
                stdscr.refresh()
                ch = stdscr.getch()
                if ch in (ord("q"), ord("Q")):
                    return 0
                continue

            mtime_age = None
            if snapshot.last_mtime is not None:
                mtime_age = now_ts - snapshot.last_mtime
            stale = mtime_age is None or mtime_age > max(8.0, refresh_interval * 6.0)

            active_train = any("train.py" in p for p in proc_lines)
            _render_header(
                stdscr,
                refresh_interval=refresh_interval,
                paused=paused,
                stale=stale,
                total_runs=snapshot.total_runs,
                target_iters=target_iters,
                active_train=active_train,
                last_score=snapshot.last_score,
                filter_label=active_filter_label,
            )

            top = 5
            bottom_h = h - top
            left_w = max(30, int(w * 0.38))
            right_w = w - left_w
            right_top_h = max(8, int(bottom_h * 0.45))
            right_bottom_h = bottom_h - right_top_h
            left_top_h = max(10, int(bottom_h * 0.56))
            left_bottom_h = bottom_h - left_top_h

            summary_win = stdscr.derwin(left_top_h, left_w, top, 0)
            events_win = stdscr.derwin(left_bottom_h, left_w, top + left_top_h, 0)
            proc_win = stdscr.derwin(right_top_h, right_w, top, left_w)
            rows_win = stdscr.derwin(right_bottom_h, right_w, top + right_top_h, left_w)

            _render_summary_panel(summary_win, snapshot)
            evt_title = "Events [focus]" if focus == "evt" else "Events"
            evt_offset = _render_scrolling_panel(events_win, evt_title, snapshot.recent_events or ["No events yet"], evt_offset, curses.color_pair(3))

            proc_title = "Processes [focus]" if focus == "proc" else "Processes"
            proc_offset = _render_scrolling_panel(proc_win, proc_title, proc_lines or ["No matching process found"], proc_offset, curses.color_pair(5))

            row_title = "Recent Results [focus]" if focus == "rows" else "Recent Results"
            row_strings = [_format_recent_row(r) for r in snapshot.recent_rows] or ["No experiment rows yet"]
            row_offset = _render_scrolling_panel(rows_win, row_title, row_strings, row_offset, curses.color_pair(1))

            stdscr.refresh()

            ch = stdscr.getch()
            if ch == -1:
                continue

            if ch in (ord("q"), ord("Q")):
                return 0
            if ch in (ord("p"), ord("P"), ord(" ")):
                paused = not paused
            elif ch in (ord("f"), ord("F")):
                filter_index = (filter_index + 1) % len(filter_presets)
                active_filter_label, active_filter_pattern = filter_presets[filter_index]
                proc_lines = active_processes(active_filter_pattern)
            elif ch == ord("+"):
                refresh_interval = max(0.2, refresh_interval - 0.2)
            elif ch == ord("-"):
                refresh_interval = min(15.0, refresh_interval + 0.2)
            elif ch in (ord("r"), ord("R")):
                snapshot = read_results(results_path, recent)
                proc_lines = active_processes(active_filter_pattern)
                next_refresh_at = now_ts + refresh_interval
            elif ch in (ord("\t"),):
                if focus == "rows":
                    focus = "proc"
                elif focus == "proc":
                    focus = "evt"
                else:
                    focus = "rows"
            elif ch in (curses.KEY_DOWN, ord("j"), ord("J")):
                if focus == "proc":
                    proc_offset += 1
                elif focus == "evt":
                    evt_offset += 1
                else:
                    row_offset += 1
            elif ch in (curses.KEY_UP, ord("k"), ord("K")):
                if focus == "proc":
                    proc_offset = max(0, proc_offset - 1)
                elif focus == "evt":
                    evt_offset = max(0, evt_offset - 1)
                else:
                    row_offset = max(0, row_offset - 1)
            elif ch == ord("g"):
                if focus == "proc":
                    proc_offset = 0
                elif focus == "evt":
                    evt_offset = 0
                else:
                    row_offset = 0
            elif ch == ord("G"):
                if focus == "proc":
                    proc_offset = 10**9
                elif focus == "evt":
                    evt_offset = 10**9
                else:
                    row_offset = 10**9

        return 0

    return curses.wrapper(_loop)


def main() -> int:
    args = parse_args()
    results_path = Path(args.results)
    if not results_path.is_absolute():
        results_path = Path.cwd() / results_path

    if args.plain:
        return _plain_snapshot(results_path=results_path, recent=args.recent, process_filter=args.process_filter)

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("Interactive mode requires a TTY. Use --plain for a one-shot snapshot.")
        return 2

    return run_monitor(
        results_path=results_path,
        interval=args.interval,
        recent=args.recent,
        process_filter=args.process_filter,
        target_iters=args.target_iters,
    )


if __name__ == "__main__":
    raise SystemExit(main())
