"""数据引擎模块：负责 SQLite 行情数据存储与 baostock 增量同步。"""

import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from sequoia_x.core.config import Settings
from sequoia_x.core.logger import get_logger

logger = get_logger(__name__)


_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS stock_daily (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol   TEXT    NOT NULL,
    date     TEXT    NOT NULL,
    open     REAL,
    high     REAL,
    low      REAL,
    close    REAL,
    volume   REAL,
    turnover REAL,
    UNIQUE (symbol, date)
);
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_symbol_date ON stock_daily (symbol, date);
"""


def _worker_fetch_batch(payload: dict) -> dict:
    """多进程 worker：独立登录，分块拉取并返回统计信息。"""
    import time as _time
    import baostock as bs

    tasks = payload["tasks"]
    end_date = payload["end_date"]
    adjustflag = payload["adjustflag"]
    max_retries = payload["max_retries"]

    login_result = None
    try:
        login_result = bs.login()
        if getattr(login_result, "error_code", "0") != "0":
            return {
                "rows": [],
                "success": 0,
                "empty": 0,
                "failed": len(tasks),
                "error_symbols": [symbol for symbol, _, _ in tasks],
                "message": getattr(login_result, "error_msg", "login failed"),
            }
    except Exception as exc:
        return {
            "rows": [],
            "success": 0,
            "empty": 0,
            "failed": len(tasks),
            "error_symbols": [symbol for symbol, _, _ in tasks],
            "message": str(exc),
        }

    rows: list[list[str | float]] = []
    success = 0
    empty = 0
    failed = 0
    error_symbols: list[str] = []

    try:
        for symbol, bs_code, start_date in tasks:
            stock_rows: list[list[str | float]] = []
            stock_ok = False
            for attempt in range(max_retries):
                try:
                    rs = bs.query_history_k_data_plus(
                        bs_code,
                        "date,open,high,low,close,volume,amount",
                        start_date=start_date,
                        end_date=end_date,
                        frequency="d",
                        adjustflag=adjustflag,
                    )
                    if rs.error_code != "0":
                        raise RuntimeError(rs.error_msg)

                    while rs.next():
                        row = rs.get_row_data()
                        if len(row) < 7 or not row[0]:
                            continue
                        stock_rows.append([symbol] + row[:7])
                    stock_ok = True
                    break
                except Exception:
                    if attempt < max_retries - 1:
                        _time.sleep(2 ** (attempt + 1))
                        try:
                            bs.logout()
                        except Exception:
                            pass
                        _time.sleep(1)
                        try:
                            relogin = bs.login()
                            if getattr(relogin, "error_code", "0") != "0":
                                break
                        except Exception:
                            break

            if not stock_ok:
                failed += 1
                error_symbols.append(symbol)
                continue

            if stock_rows:
                rows.extend(stock_rows)
                success += 1
            else:
                empty += 1
    finally:
        try:
            bs.logout()
        except Exception:
            pass

    return {
        "rows": rows,
        "success": success,
        "empty": empty,
        "failed": failed,
        "error_symbols": error_symbols,
        "message": "",
    }


class DataEngine:
    """行情数据引擎，负责 SQLite 存储和 baostock 数据同步。"""

    def __init__(self, settings: Settings) -> None:
        self.db_path: str = settings.db_path
        self.start_date: str = settings.start_date
        self.state_path: Path = Path(self.db_path).with_suffix(".sync_state.json")
        self._init_db()

    def _init_db(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(_CREATE_TABLE_SQL)
            conn.execute(_CREATE_INDEX_SQL)
            conn.commit()
        logger.info(f"数据库初始化完成：{self.db_path}")

    def _get_last_date(self, symbol: str) -> str | None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT MAX(date) FROM stock_daily WHERE symbol = ?",
                (symbol,),
            ).fetchone()
        return row[0] if row and row[0] else None

    def get_ohlcv(self, symbol: str) -> pd.DataFrame:
        with sqlite3.connect(self.db_path) as conn:
            df = pd.read_sql(
                "SELECT * FROM stock_daily WHERE symbol = ? ORDER BY date",
                conn,
                params=(symbol,),
            )
        return df

    @staticmethod
    def _to_baostock_code(symbol: str) -> str:
        """将纯数字代码转为 baostock 格式。"""
        if symbol.startswith("920") or symbol.startswith(("4", "8")):
            return f"bj.{symbol}"
        prefix = "sh" if symbol.startswith(("6", "9")) else "sz"
        return f"{prefix}.{symbol}"

    @staticmethod
    def _chunked(items: list[tuple[str, str, str]], chunk_size: int) -> list[list[tuple[str, str, str]]]:
        return [items[i:i + chunk_size] for i in range(0, len(items), chunk_size)]

    def _load_sync_state(self) -> dict:
        if not self.state_path.exists():
            return {}
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_sync_state(self, state: dict) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _clear_sync_state(self) -> None:
        try:
            self.state_path.unlink(missing_ok=True)
        except Exception:
            pass

    def _get_local_symbol_dates(self) -> dict[str, str]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT symbol, MAX(date) FROM stock_daily GROUP BY symbol"
            ).fetchall()
        return {symbol: last_date for symbol, last_date in rows if last_date}

    def _write_rows(self, rows: list[list[str | float]]) -> int:
        if not rows:
            return 0

        clean_rows: list[tuple[str, str, float, float, float, float, float, float]] = []
        for row in rows:
            try:
                symbol = str(row[0])
                trade_date = str(row[1])
                open_price = float(row[2])
                high_price = float(row[3])
                low_price = float(row[4])
                close_price = float(row[5])
                volume_raw = row[6] if len(row) > 6 else ''
                turnover_raw = row[7] if len(row) > 7 else ''
                volume = float(volume_raw) if volume_raw not in ('', None) else 0.0
                turnover = float(turnover_raw) if turnover_raw not in ('', None) else 0.0
            except (TypeError, ValueError, IndexError):
                continue

            if not trade_date or close_price <= 0:
                continue

            clean_rows.append(
                (
                    symbol,
                    trade_date,
                    open_price,
                    high_price,
                    low_price,
                    close_price,
                    volume,
                    turnover,
                )
            )

        if not clean_rows:
            return 0

        with sqlite3.connect(self.db_path, timeout=60) as conn:
            conn.execute("PRAGMA busy_timeout=60000")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executemany(
                """
                INSERT OR REPLACE INTO stock_daily
                (symbol, date, open, high, low, close, volume, turnover)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                clean_rows,
            )
            conn.commit()
        return len(clean_rows)

    def _run_sync_tasks(
        self,
        tasks: list[tuple[str, str, str]],
        end_date: str,
        *,
        mode: str,
        chunk_size: int = 150,
        workers: int = 4,
        max_retries: int = 3,
        adjustflag: str = "3",
        resume: bool = True,
        max_chunks: int | None = None,
    ) -> dict:
        from multiprocessing import Pool

        if not tasks:
            logger.info(f"{mode}: 无需同步")
            return {
                "mode": mode,
                "requested": 0,
                "processed": 0,
                "written": 0,
                "success": 0,
                "empty": 0,
                "failed": 0,
                "remaining": 0,
            }

        all_chunks = self._chunked(tasks, chunk_size)
        state = self._load_sync_state() if resume else {}
        state_chunks = state.get("chunks", []) if state.get("mode") == mode and state.get("end_date") == end_date else []
        pending_chunks = state_chunks if state_chunks else all_chunks
        if max_chunks is not None:
            pending_chunks = pending_chunks[:max_chunks]

        total_requested = sum(len(chunk) for chunk in pending_chunks)
        total_processed = 0
        total_written = 0
        total_success = 0
        total_empty = 0
        total_failed = 0
        remaining_chunks: list[list[tuple[str, str, str]]] = []

        logger.info(
            f"{mode}: 待处理 {len(pending_chunks)} 个分块 / {total_requested} 只股票，"
            f"workers={min(workers, len(pending_chunks))}, chunk_size={chunk_size}"
        )

        active_workers = min(workers, len(pending_chunks))
        for batch_start in range(0, len(pending_chunks), active_workers):
            batch_chunks = pending_chunks[batch_start:batch_start + active_workers]
            payloads = [
                {
                    "tasks": chunk,
                    "end_date": end_date,
                    "adjustflag": adjustflag,
                    "max_retries": max_retries,
                }
                for chunk in batch_chunks
            ]

            with Pool(len(batch_chunks)) as pool:
                results = pool.map(_worker_fetch_batch, payloads)

            for chunk, result in zip(batch_chunks, results):
                processed = len(chunk)
                total_processed += processed
                total_success += result["success"]
                total_empty += result["empty"]
                total_failed += result["failed"]
                total_written += self._write_rows(result["rows"])

                if result["failed"] > 0:
                    failed_symbols = set(result["error_symbols"])
                    retry_chunk = [task for task in chunk if task[0] in failed_symbols]
                    if retry_chunk:
                        remaining_chunks.append(retry_chunk)

                logger.info(
                    f"{mode}: 已处理 {total_processed}/{total_requested} 只，"
                    f"成功 {total_success}，空结果 {total_empty}，失败 {total_failed}，写入 {total_written} 行"
                )

        if remaining_chunks:
            self._save_sync_state(
                {
                    "mode": mode,
                    "end_date": end_date,
                    "chunk_size": chunk_size,
                    "workers": workers,
                    "chunks": remaining_chunks,
                }
            )
        else:
            self._clear_sync_state()

        summary = {
            "mode": mode,
            "requested": total_requested,
            "processed": total_processed,
            "written": total_written,
            "success": total_success,
            "empty": total_empty,
            "failed": total_failed,
            "remaining": sum(len(chunk) for chunk in remaining_chunks),
        }
        logger.info(
            f"{mode}: 完成，请求 {summary['requested']}，成功 {summary['success']}，"
            f"失败 {summary['failed']}，剩余 {summary['remaining']}，写入 {summary['written']} 行"
        )
        return summary

    def sync_today_bulk(
        self,
        *,
        workers: int = 4,
        chunk_size: int = 150,
        max_retries: int = 3,
        lookback_days: int = 3,
        resume: bool = True,
        max_chunks: int | None = None,
    ) -> dict:
        """日常增量同步：只处理近期落后股票，支持分块、重试、断点续传。"""
        target_day = date.today() - timedelta(days=1)
        today_str = target_day.strftime("%Y-%m-%d")
        local_dates = self._get_local_symbol_dates()
        if not local_dates:
            logger.warning("本地无股票数据，请先执行历史补洞")
            return {
                "mode": "incremental",
                "requested": 0,
                "processed": 0,
                "written": 0,
                "success": 0,
                "empty": 0,
                "failed": 0,
                "remaining": 0,
            }

        tasks: list[tuple[str, str, str]] = []
        cutoff = target_day - timedelta(days=lookback_days)
        for symbol, last_date in local_dates.items():
            last_dt = date.fromisoformat(last_date)
            if last_dt >= target_day:
                continue
            if last_dt < cutoff:
                continue
            start_date = (last_dt + timedelta(days=1)).strftime("%Y-%m-%d")
            tasks.append((symbol, self._to_baostock_code(symbol), start_date))

        return self._run_sync_tasks(
            tasks,
            today_str,
            mode="incremental",
            chunk_size=chunk_size,
            workers=workers,
            max_retries=max_retries,
            adjustflag="3",
            resume=resume,
            max_chunks=max_chunks,
        )

    def repair_history(
        self,
        symbols: list[str] | None = None,
        *,
        workers: int = 4,
        chunk_size: int = 120,
        max_retries: int = 3,
        stale_before_days: int = 3,
        resume: bool = True,
        max_chunks: int | None = None,
    ) -> dict:
        """历史补洞：只处理明显落后的股票，支持分块、重试、断点续传。"""
        target_day = date.today() - timedelta(days=1)
        today_str = target_day.strftime("%Y-%m-%d")
        local_dates = self._get_local_symbol_dates()
        if not local_dates:
            logger.warning("本地无股票数据，请先准备股票列表后回填")
            return {
                "mode": "repair",
                "requested": 0,
                "processed": 0,
                "written": 0,
                "success": 0,
                "empty": 0,
                "failed": 0,
                "remaining": 0,
            }

        target_symbols = symbols or list(local_dates.keys())
        cutoff = target_day - timedelta(days=stale_before_days)
        tasks: list[tuple[str, str, str]] = []
        explicit_symbols = symbols is not None
        for symbol in target_symbols:
            last_date = local_dates.get(symbol)
            if not last_date:
                start_date = self.start_date
            else:
                last_dt = date.fromisoformat(last_date)
                if not explicit_symbols and last_dt >= cutoff:
                    continue
                if last_dt >= target_day:
                    continue
                start_date = (last_dt + timedelta(days=1)).strftime("%Y-%m-%d")
            tasks.append((symbol, self._to_baostock_code(symbol), start_date))

        return self._run_sync_tasks(
            tasks,
            today_str,
            mode="repair",
            chunk_size=chunk_size,
            workers=workers,
            max_retries=max_retries,
            adjustflag="3",
            resume=resume,
            max_chunks=max_chunks,
        )

    def backfill(self, symbols: list[str]) -> None:
        """兼容旧入口：转到历史补洞模式。"""
        summary = self.repair_history(symbols=symbols)
        logger.info(
            f"历史补洞完成 — 成功: {summary['success']} | 空结果: {summary['empty']} | 失败: {summary['failed']}"
        )

    def get_all_symbols(self) -> list[str]:
        """通过 baostock 获取全市场 A 股代码列表。"""
        import baostock as bs

        lg = bs.login()
        if lg.error_code != "0":
            logger.error(f"baostock 登录失败: {lg.error_msg}")
            return []

        try:
            rs = bs.query_stock_basic(code_name="", code="")
            symbols = []
            while rs.next():
                row = rs.get_row_data()
                code = row[0]
                status = row[4]
                stock_type = row[5]
                if status == "1" and stock_type == "1":
                    symbols.append(code.split(".")[1])
            logger.info(f"获取股票列表完成，共 {len(symbols)} 只")
            return symbols
        except Exception as exc:
            logger.error(f"获取股票列表失败: {exc}")
            return []
        finally:
            bs.logout()

    def get_local_symbols(self) -> list[str]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT DISTINCT symbol FROM stock_daily"
            ).fetchall()
        return [row[0] for row in rows]
