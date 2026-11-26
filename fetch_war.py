import os
import sys
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
import pandas as pd
import requests

CLANS = [
    {"name": "萌面打劫", "tag": "#2YR9JVCG8"},
    {"name": "萌虎下山", "tag": "#2JLC9Q8LL"},
    {"name": "小倔强", "tag": "#2CVRYQ9C"},
]

API_TOKEN = os.getenv("COC_API_TOKEN", "").strip()
API_BASE = os.getenv("COC_API_BASE", "https://cocproxy.royaleapi.dev/v1").rstrip("/")
WAR_HISTORY_FILE = "war_history.csv"
CWL_HISTORY_FILE = "cwl_history.csv"
GOOGLE_SHEET_WEBHOOK_URL = os.getenv("GOOGLE_SHEET_WEBHOOK_URL", "").strip()

WAR_COLUMNS = [
    "clan_tag",
    "clan_name",
    "war_id",
    "war_state",
    "start_time",
    "end_time",
    "opponent_name",
    "team_size",
    "attacks_per_member",
    "player_tag",
    "player_name",
    "town_hall",
    "map_position",
    "attacks_used",
    "attacks_missed",
    "total_stars",
    "total_destruction",
    "three_stars",
    "two_stars",
    "one_stars",
    "zero_stars",
    "updated_at_utc",
]

CWL_COLUMNS = [
    "clan_tag",
    "clan_name",
    "season",
    "round_num",
    "war_tag",
    "war_state",
    "opponent_name",
    "team_size",
    "player_tag",
    "player_name",
    "town_hall",
    "map_position",
    "attacks_used",
    "attacks_missed",
    "stars",
    "destruction",
    "updated_at_utc",
]


def api_get(path: str, token: str) -> dict | None:
    if not token:
        raise RuntimeError("未检测到 COC_API_TOKEN 环境变量，请先在 GitHub Secrets 中配置。")
    url = f"{API_BASE}{path}"
    resp = requests.get(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=20,
    )
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        raise RuntimeError(f"API 请求失败 {path} (HTTP {resp.status_code}): {resp.text}")
    return resp.json()


def fetch_regular_war(clan_tag: str, default_name: str, token: str) -> pd.DataFrame:
    encoded_tag = urllib.parse.quote(clan_tag)
    data = api_get(f"/clans/{encoded_tag}/currentwar", token)
    if not data:
        return pd.DataFrame(columns=WAR_COLUMNS)

    state = data.get("state", "notInWar")
    if state not in ("inWar", "warEnded"):
        print(f"[常规战 | {default_name}] 状态为 {state}，跳过记录。")
        return pd.DataFrame(columns=WAR_COLUMNS)

    war_id = data.get("preparationStartTime", "")
    start_time = data.get("startTime", "")
    end_time = data.get("endTime", "")
    team_size = int(data.get("teamSize", 0))
    attacks_per_member = int(data.get("attacksPerMember", 2))

    clan = data.get("clan", {})
    opponent = data.get("opponent", {})
    clan_name = clan.get("name", default_name)
    opponent_name = opponent.get("name", "未知对手")
    members = clan.get("members", [])

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    rows = []

    for m in members:
        attacks = m.get("attacks", []) or []
        used = len(attacks)
        missed = max(0, attacks_per_member - used)
        stars = sum(int(a.get("stars", 0)) for a in attacks)
        dest = sum(float(a.get("destructionPercentage", 0.0)) for a in attacks)
        s3 = sum(1 for a in attacks if int(a.get("stars", 0)) == 3)
        s2 = sum(1 for a in attacks if int(a.get("stars", 0)) == 2)
        s1 = sum(1 for a in attacks if int(a.get("stars", 0)) == 1)
        s0 = sum(1 for a in attacks if int(a.get("stars", 0)) == 0)

        rows.append({
            "clan_tag": clan_tag,
            "clan_name": clan_name,
            "war_id": war_id,
            "war_state": state,
            "start_time": start_time,
            "end_time": end_time,
            "opponent_name": opponent_name,
            "team_size": team_size,
            "attacks_per_member": attacks_per_member,
            "player_tag": m.get("tag", ""),
            "player_name": m.get("name", ""),
            "town_hall": int(m.get("townhallLevel", 0)),
            "map_position": int(m.get("mapPosition", 0)),
            "attacks_used": used,
            "attacks_missed": missed,
            "total_stars": stars,
            "total_destruction": round(dest, 1),
            "three_stars": s3,
            "two_stars": s2,
            "one_stars": s1,
            "zero_stars": s0,
            "updated_at_utc": now_utc,
        })

    return pd.DataFrame(rows, columns=WAR_COLUMNS)


def update_war_csv(all_new_dfs: list, filepath: str = WAR_HISTORY_FILE) -> pd.DataFrame:
    if os.path.exists(filepath):
        old_df = pd.read_csv(filepath)
        if "clan_tag" not in old_df.columns:
            old_df["clan_tag"] = "#2YR9JVCG8"
    else:
        old_df = pd.DataFrame(columns=WAR_COLUMNS)

    valid_dfs = [d for d in all_new_dfs if not d.empty]
    if not valid_dfs:
        if not os.path.exists(filepath):
            old_df.to_csv(filepath, index=False, encoding="utf-8-sig")
        return old_df

    combined_new = pd.concat(valid_dfs, ignore_index=True)

    if not old_df.empty:
        new_keys = set(zip(combined_new["clan_tag"].astype(str), combined_new["war_id"].astype(str)))
        mask_keep = [
            (str(ct), str(wid)) not in new_keys
            for ct, wid in zip(old_df["clan_tag"].astype(str), old_df["war_id"].astype(str))
        ]
        old_df = old_df[mask_keep]

    final_df = pd.concat([old_df, combined_new], ignore_index=True)
    final_df = final_df.sort_values(by=["clan_tag", "war_id", "map_position"], ascending=[True, True, True])
    final_df.to_csv(filepath, index=False, encoding="utf-8-sig")
    print(f"[常规战] 历史库已更新，本次写入 {len(combined_new)} 条记录。")
    return final_df


def fetch_cwl_season(clan_tag: str, default_name: str, token: str) -> pd.DataFrame:
    encoded_tag = urllib.parse.quote(clan_tag)
    group = api_get(f"/clans/{encoded_tag}/currentwar/leaguegroup", token)
    if not group or group.get("state") == "notInWar":
        print(f"[联赛 | {default_name}] 当前不在联赛期间，跳过。")
        return pd.DataFrame(columns=CWL_COLUMNS)

    season = str(group.get("season", datetime.now(timezone.utc).strftime("%Y-%m")))
    rounds = group.get("rounds", [])
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    rows = []

    for r_idx, rnd in enumerate(rounds, start=1):
        war_tags = rnd.get("warTags", [])
        for w_tag in war_tags:
            if not w_tag or w_tag == "#0":
                continue
            enc_w = urllib.parse.quote(w_tag)
            w_data = api_get(f"/clanwarleagues/wars/{enc_w}", token)
            if not w_data:
                continue

            c1 = w_data.get("clan", {})
            c2 = w_data.get("opponent", {})
            if str(c1.get("tag", "")).upper() == clan_tag.upper():
                our_clan, opp_clan = c1, c2
            elif str(c2.get("tag", "")).upper() == clan_tag.upper():
                our_clan, opp_clan = c2, c1
            else:
                continue

            w_state = w_data.get("state", "preparation")
            if w_state not in ("inWar", "warEnded"):
                break

            team_size = int(w_data.get("teamSize", 15))
            clan_name = our_clan.get("name", default_name)
            opp_name = opp_clan.get("name", "未知对手")

            for m in our_clan.get("members", []):
                atks = m.get("attacks", []) or []
                used = len(atks)
                missed = max(0, 1 - used)
                stars = sum(int(a.get("stars", 0)) for a in atks)
                dest = sum(float(a.get("destructionPercentage", 0.0)) for a in atks)

                rows.append({
                    "clan_tag": clan_tag,
                    "clan_name": clan_name,
                    "season": season,
                    "round_num": r_idx,
                    "war_tag": w_tag,
                    "war_state": w_state,
                    "opponent_name": opp_name,
                    "team_size": team_size,
                    "player_tag": m.get("tag", ""),
                    "player_name": m.get("name", ""),
                    "town_hall": int(m.get("townhallLevel", 0)),
                    "map_position": int(m.get("mapPosition", 0)),
                    "attacks_used": used,
                    "attacks_missed": missed,
                    "stars": stars,
                    "destruction": round(dest, 1),
                    "updated_at_utc": now_utc,
                })
            break

    return pd.DataFrame(rows, columns=CWL_COLUMNS)


def update_cwl_csv(all_cwl_dfs: list, filepath: str = CWL_HISTORY_FILE) -> pd.DataFrame:
    if os.path.exists(filepath):
        old_df = pd.read_csv(filepath)
    else:
        old_df = pd.DataFrame(columns=CWL_COLUMNS)

    valid_dfs = [d for d in all_cwl_dfs if not d.empty]
    if not valid_dfs:
        if not os.path.exists(filepath):
            old_df.to_csv(filepath, index=False, encoding="utf-8-sig")
        return old_df

    combined_new = pd.concat(valid_dfs, ignore_index=True)

    if not old_df.empty:
        new_keys = set(
            zip(
                combined_new["clan_tag"].astype(str),
                combined_new["season"].astype(str),
                combined_new["round_num"].astype(int),
            )
        )
        mask_keep = [
            (str(ct), str(sn), int(rn)) not in new_keys
            for ct, sn, rn in zip(
                old_df["clan_tag"].astype(str),
                old_df["season"].astype(str),
                old_df["round_num"].astype(int),
            )
        ]
        old_df = old_df[mask_keep]

    final_df = pd.concat([old_df, combined_new], ignore_index=True)
    final_df = final_df.sort_values(
        by=["clan_tag", "season", "round_num", "map_position"],
        ascending=[True, True, True, True],
    )
    final_df.to_csv(filepath, index=False, encoding="utf-8-sig")
    print(f"[七天联赛] 历史库已更新，本次写入 {len(combined_new)} 条记录。")
    return final_df


def build_war_15_summary(war_df: pd.DataFrame) -> pd.DataFrame:
    if war_df.empty:
        return pd.DataFrame()
    sum_list = []
    for _, sub_c in war_df.groupby("clan_tag"):
        wars = sorted(sub_c["war_id"].astype(str).unique().tolist())[-15:]
        sub_15 = sub_c[sub_c["war_id"].astype(str).isin(wars)]
        g = (
            sub_15.groupby(["clan_name", "clan_tag", "player_tag", "player_name"], as_index=False)
            .agg(
                大本营=("town_hall", "max"),
                参战场次=("war_id", "nunique"),
                应出刀数=("attacks_per_member", "sum"),
                实际出刀=("attacks_used", "sum"),
                漏打刀数=("attacks_missed", "sum"),
                总得星=("total_stars", "sum"),
            )
        )
        g["漏刀率(%)"] = (g["漏打刀数"] / g["应出刀数"] * 100).round(1)
        g = g.sort_values(by=["漏打刀数", "漏刀率(%)"], ascending=[False, False])
        sum_list.append(g)
    return pd.concat(sum_list, ignore_index=True) if sum_list else pd.DataFrame()


def build_cwl_7day_summary(cwl_df: pd.DataFrame) -> pd.DataFrame:
    if cwl_df.empty:
        return pd.DataFrame()

    summary_rows = []
    for (clan_tag, clan_name, season), grp in cwl_df.groupby(["clan_tag", "clan_name", "season"]):
        players = (
            grp.groupby(["player_tag", "player_name"], as_index=False)
            .agg(
                大本营=("town_hall", "max"),
                上场天数=("round_num", "nunique"),
                已出刀数=("attacks_used", "sum"),
                漏打刀数=("attacks_missed", "sum"),
                联赛总星=("stars", "sum"),
            )
        )
        day_lookup = {}
        for _, r in grp.iterrows():
            key = (r["player_tag"], int(r["round_num"]))
            if int(r["attacks_used"]) > 0:
                day_lookup[key] = f"{int(r['stars'])}★"
            elif str(r["war_state"]) == "warEnded":
                day_lookup[key] = "❌漏"
            else:
                day_lookup[key] = "⏳待"

        for _, p in players.iterrows():
            ptag = p["player_tag"]
            row_dict = {
                "部落名称": clan_name,
                "部落标签": clan_tag,
                "赛季": season,
                "成员名称": p["player_name"],
                "玩家标签": ptag,
                "大本营": int(p["大本营"]),
                "上场天数": int(p["上场天数"]),
                "已出刀": int(p["已出刀数"]),
                "漏打": int(p["漏打刀数"]),
                "总得星": int(p["联赛总星"]),
                "满8星": "✅是" if int(p["联赛总星"]) >= 8 else "未满",
            }
            for d in range(1, 8):
                row_dict[f"DAY {d}"] = day_lookup.get((ptag, d), "—")
            summary_rows.append(row_dict)

    out = pd.DataFrame(summary_rows)
    if not out.empty:
        out = out.sort_values(
            by=["部落标签", "赛季", "漏打", "总得星"],
            ascending=[True, False, False, False],
        )
    return out


def df_to_rows(df: pd.DataFrame) -> list:
    if df.empty:
        return []
    clean_df = df.fillna("")
    return [clean_df.columns.tolist()] + clean_df.astype(str).values.tolist()


def sync_to_google_sheet(war_df: pd.DataFrame, cwl_df: pd.DataFrame) -> None:
    if not GOOGLE_SHEET_WEBHOOK_URL:
        print("[Google Sheet 备份] 未配置 GOOGLE_SHEET_WEBHOOK_URL，跳过云端同步。")
        return

    tabs_payload = {}
    war_sum = build_war_15_summary(war_df)
    cwl_sum = build_cwl_7day_summary(cwl_df)

    if not cwl_sum.empty:
        tabs_payload["七天联赛_汇总"] = df_to_rows(cwl_sum)
    if not cwl_df.empty:
        tabs_payload["七天联赛_每日明细"] = df_to_rows(cwl_df)
    if not war_sum.empty:
        tabs_payload["常规战_近15场汇总"] = df_to_rows(war_sum)
    if not war_df.empty:
        tabs_payload["常规战_原始明细"] = df_to_rows(war_df)

    if not tabs_payload:
        return

    try:
        resp = requests.post(
            GOOGLE_SHEET_WEBHOOK_URL,
            json={"tabs": tabs_payload},
            timeout=30,
        )
        if resp.status_code == 200:
            print(f"[Google Sheet 备份] 已成功写入云端表格：{resp.text[:100]}")
        else:
            print(f"[Google Sheet 备份警告] 返回异常 ({resp.status_code}): {resp.text}", file=sys.stderr)
    except Exception as exc:
        print(f"[Google Sheet 备份警告] 请求失败（不影响 GitHub CSV 存档）: {exc}", file=sys.stderr)


def parse_end_time_utc(end_time_str: str) -> datetime | None:
    s = str(end_time_str or "").strip()
    try:
        if len(s) >= 15 and "T" in s:
            return datetime.strptime(s[:15], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
    except Exception:
        return None
    return None


def find_imminent_war_end(war_list: list, window_sec: int = 900) -> tuple[str, datetime] | None:
    """检查三个部落中是否有处于战斗日(inWar)且距离结束 <= 15分钟的对局"""
    now_utc = datetime.now(timezone.utc)
    earliest_target = None

    for df_w in war_list:
        if df_w is None or df_w.empty:
            continue
        state = str(df_w["war_state"].iloc[0]).strip()
        if state != "inWar":
            continue
        end_dt = parse_end_time_utc(df_w["end_time"].iloc[0])
        if end_dt is None:
            continue
        rem = (end_dt - now_utc).total_seconds()
        if 0 < rem <= window_sec:
            c_name = str(df_w["clan_name"].iloc[0])
            if earliest_target is None or end_dt < earliest_target[1]:
                earliest_target = (c_name, end_dt)

    return earliest_target


def run_sync_once() -> tuple[list, list, bool]:
    war_list = []
    cwl_list = []
    has_error = False

    for item in CLANS:
        c_name = item["name"]
        c_tag = item["tag"].strip().upper()
        if not c_tag.startswith("#"):
            c_tag = "#" + c_tag

        try:
            df_w = fetch_regular_war(c_tag, c_name, API_TOKEN)
            war_list.append(df_w)
            if not df_w.empty:
                print(f"[常规战 | {c_name}] 抓拍成功（状态: {df_w['war_state'].iloc[0]}，{len(df_w)}人）")
        except Exception as exc:
            print(f"[常规战 | {c_name}] 抓取警告: {exc}", file=sys.stderr)
            has_error = True

        try:
            df_cwl = fetch_cwl_season(c_tag, c_name, API_TOKEN)
            cwl_list.append(df_cwl)
            if not df_cwl.empty:
                print(f"[联赛 | {c_name}] 抓拍成功（赛季: {df_cwl['season'].iloc[0]}，累计 {len(df_cwl)} 人次）")
        except Exception as exc:
            print(f"[联赛 | {c_name}] 抓取警告: {exc}", file=sys.stderr)

    full_war_df = update_war_csv(war_list, WAR_HISTORY_FILE)
    full_cwl_df = update_cwl_csv(cwl_list, CWL_HISTORY_FILE)
    sync_to_google_sheet(full_war_df, full_cwl_df)

    return war_list, cwl_list, has_error


if __name__ == "__main__":
    start_run_utc = datetime.now(timezone.utc)
    war_list, cwl_list, has_error = run_sync_once()

    # 赛末最后 15 分钟原地蹲点模式：防止副队秒开下一场导致漏抓压哨出刀
    while True:
        # 安全上限：单次运行最多蹲点 25 分钟，避免进程超时
        if (datetime.now(timezone.utc) - start_run_utc).total_seconds() > 1500:
            break

        imminent = find_imminent_war_end(war_list, window_sec=900)
        if imminent is None:
            break

        target_clan, end_dt = imminent
        # 依次在 结束前60秒 -> 结束前15秒 -> 结束后15秒 精准抓拍
        for offset_sec in (60, 15, -15):
            checkpoint_dt = end_dt - timedelta(seconds=offset_sec)
            sleep_sec = (checkpoint_dt - datetime.now(timezone.utc)).total_seconds()
            if sleep_sec > 0:
                label = f"结束前{offset_sec}秒" if offset_sec > 0 else f"结束后{abs(offset_sec)}秒"
                print(f"⏳ [赛末蹲点 | {target_clan}] 等待 {sleep_sec:.1f} 秒，将于{label}精准抓拍...")
                time.sleep(sleep_sec)
                war_list, cwl_list, has_error = run_sync_once()

    if has_error and not war_list and not cwl_list:
        sys.exit(1)
