"""US market calendar helpers.

The user can run the system from Spain, but the traded venue is the US market.
This module evaluates sessions in the exchange calendar and returns explicit
market-open context for every scheduled job.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class MarketStatus:
    is_open: bool
    now_utc: str
    now_local: str
    now_market: str
    calendar: str
    session_date: str | None
    market_open: str | None
    market_close: str | None
    next_open: str | None
    next_close: str | None
    reason: str

    def as_dict(self) -> dict[str, str | bool | None]:
        return {
            "is_open": self.is_open,
            "now_utc": self.now_utc,
            "now_local": self.now_local,
            "now_market": self.now_market,
            "calendar": self.calendar,
            "session_date": self.session_date,
            "market_open": self.market_open,
            "market_close": self.market_close,
            "next_open": self.next_open,
            "next_close": self.next_close,
            "reason": self.reason,
        }


class MarketCalendar:
    def __init__(self, calendar_name: str = "XNYS", local_timezone: str = "Europe/Madrid") -> None:
        self.calendar_name = calendar_name
        self.local_tz = ZoneInfo(local_timezone)
        self.market_tz = ZoneInfo("America/New_York")
        self._calendar = self._load_calendar(calendar_name)

    @staticmethod
    def _load_calendar(calendar_name: str):
        try:
            import pandas_market_calendars as mcal

            return mcal.get_calendar(calendar_name)
        except Exception:
            return None

    def status(self, now: datetime | None = None) -> MarketStatus:
        now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        now_local = now_utc.astimezone(self.local_tz)
        now_market = now_utc.astimezone(self.market_tz)

        if self._calendar is None:
            return self._fallback_status(now_utc, now_local, now_market)

        start = (now_market.date() - timedelta(days=7)).isoformat()
        end = (now_market.date() + timedelta(days=14)).isoformat()
        schedule = self._calendar.schedule(start_date=start, end_date=end)

        current_session = None
        next_session = None
        for session_date, row in schedule.iterrows():
            market_open = row["market_open"].to_pydatetime().astimezone(timezone.utc)
            market_close = row["market_close"].to_pydatetime().astimezone(timezone.utc)
            if market_open <= now_utc <= market_close:
                current_session = (session_date, market_open, market_close)
                break
            if market_open > now_utc and next_session is None:
                next_session = (session_date, market_open, market_close)

        if current_session:
            session_date, market_open, market_close = current_session
            return MarketStatus(
                is_open=True,
                now_utc=now_utc.isoformat(),
                now_local=now_local.isoformat(),
                now_market=now_market.isoformat(),
                calendar=self.calendar_name,
                session_date=str(session_date.date()),
                market_open=market_open.astimezone(self.local_tz).isoformat(),
                market_close=market_close.astimezone(self.local_tz).isoformat(),
                next_open=None,
                next_close=market_close.astimezone(self.local_tz).isoformat(),
                reason="NYSE regular session is open.",
            )

        if next_session:
            session_date, market_open, market_close = next_session
            return MarketStatus(
                is_open=False,
                now_utc=now_utc.isoformat(),
                now_local=now_local.isoformat(),
                now_market=now_market.isoformat(),
                calendar=self.calendar_name,
                session_date=None,
                market_open=None,
                market_close=None,
                next_open=market_open.astimezone(self.local_tz).isoformat(),
                next_close=market_close.astimezone(self.local_tz).isoformat(),
                reason=f"Market closed. Next session is {session_date.date()}.",
            )

        return MarketStatus(
            is_open=False,
            now_utc=now_utc.isoformat(),
            now_local=now_local.isoformat(),
            now_market=now_market.isoformat(),
            calendar=self.calendar_name,
            session_date=None,
            market_open=None,
            market_close=None,
            next_open=None,
            next_close=None,
            reason="Market closed. No upcoming session found in lookup window.",
        )

    def is_trading_day(self, day: datetime | None = None) -> bool:
        now_utc = (day or datetime.now(timezone.utc)).astimezone(timezone.utc)
        market_day = now_utc.astimezone(self.market_tz).date()
        if self._calendar is None:
            return market_day.weekday() < 5
        schedule = self._calendar.schedule(start_date=market_day.isoformat(), end_date=market_day.isoformat())
        return not schedule.empty

    def should_run_daily_study(self, now: datetime | None = None) -> tuple[bool, MarketStatus]:
        status = self.status(now)
        now_utc = datetime.fromisoformat(status.now_utc)
        market_now = now_utc.astimezone(self.market_tz)
        if not self.is_trading_day(now_utc):
            return False, status
        if status.is_open:
            return False, status

        if self._calendar is None:
            after_close = market_now.time() >= time(16, 0)
            return after_close, status

        start = market_now.date().isoformat()
        schedule = self._calendar.schedule(start_date=start, end_date=start)
        if schedule.empty:
            return False, status
        close_utc = schedule.iloc[0]["market_close"].to_pydatetime().astimezone(timezone.utc)
        return now_utc >= close_utc, status

    def _fallback_status(
        self,
        now_utc: datetime,
        now_local: datetime,
        now_market: datetime,
    ) -> MarketStatus:
        weekday = now_market.weekday()
        regular_open = now_market.replace(hour=9, minute=30, second=0, microsecond=0)
        regular_close = now_market.replace(hour=16, minute=0, second=0, microsecond=0)
        is_regular_weekday = weekday < 5
        is_open = is_regular_weekday and regular_open <= now_market <= regular_close
        next_open = regular_open
        if now_market >= regular_close or weekday >= 5:
            days = 1
            while (now_market + timedelta(days=days)).weekday() >= 5:
                days += 1
            next_open = (now_market + timedelta(days=days)).replace(hour=9, minute=30, second=0, microsecond=0)
        elif now_market < regular_open:
            next_open = regular_open

        return MarketStatus(
            is_open=is_open,
            now_utc=now_utc.isoformat(),
            now_local=now_local.isoformat(),
            now_market=now_market.isoformat(),
            calendar=f"{self.calendar_name}-fallback",
            session_date=now_market.date().isoformat() if is_open else None,
            market_open=regular_open.astimezone(self.local_tz).isoformat() if is_open else None,
            market_close=regular_close.astimezone(self.local_tz).isoformat() if is_open else None,
            next_open=None if is_open else next_open.astimezone(self.local_tz).isoformat(),
            next_close=regular_close.astimezone(self.local_tz).isoformat() if is_open else None,
            reason="Fallback weekday/time calendar used; exchange holidays are not available.",
        )
