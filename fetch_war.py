import json
import os
import sys
import urllib.parse
from datetime import datetime, timezone
import pandas as pd
import requests

# 三个部落配置
CLANS = [
    {"name": "萌面打劫", "tag": "#2YR9JVCG8"},
    {"name": "萌虎下山", "tag": "#2JLC9Q8LL"},
    {"name": "小倔强", "tag": "#2CVRYQ9C"},
]

API_TOKEN = os.getenv("COC_API_TOKEN", "").strip()
API_BASE = os.getenv("COC_API_BASE", "https://cocproxy.royaleapi.dev/v1").rstrip("/")
WAR_HISTORY_FILE = "war_history.csv"
CWL_HISTORY_FILE = "cwl_history.csv"

GOOGLE_SA_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "").strip()

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


# ==============================================================================
# 1. 常规部落战抓拍
# ==============================================================================
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


# ==============================================================================
# 2. 七天部落对战联赛 (CWL) 抓拍
# ==============================================================================
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


# ==============================================================================
# 3. 后台自动备份到 Google Sheet
# ==============================================================================
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


def sync_to_google_sheet(war_df: pd.DataFrame, cwl_df: pd.DataFrame) -> None:
    if not GOOGLE_SA_JSON or not GOOGLE_SHEET_ID:
        print("[Google Sheet 备份] 未配置密钥，跳过云端表格同步。")
        return

    try:
        import gspread
        from google.oauth2.service_account import Credentials

        creds_dict = json.loads(GOOGLE_SA_JSON)
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(GOOGLE_SHEET_ID)

        def write_tab(tab_name: str, df: pd.DataFrame):
            if df.empty:
                return
            clean_df = df.fillna("")
            try:
                ws = sh.worksheet(tab_name)
            except gspread.WorksheetNotFound:
                ws = sh.add_worksheet(title=tab_name, rows=max(200, len(clean_df) + 20), cols=max(25, len(clean_df.columns) + 2))
            ws.clear()
            values = [clean_df.columns.tolist()] + clean_df.astype(str).values.tolist()
            ws.update(range_name="A1", values=values)

        if not war_df.empty:
            sum_list = []
            for c_tag, sub_c in war_df.groupby("clan_tag"):
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
            if sum_list:
                write_tab("常规战_近15场汇总", pd.concat(sum_list, ignore_index=True))
            write_tab("常规战_原始明细", war_df)

        if not cwl_df.empty:
            cwl_sum = build_cwl_7day_summary(cwl_df)
            write_tab("七天联赛_汇总", cwl_sum)
            write_tab("七天联赛_每日明细", cwl_df)

        print("[Google Sheet 备份] 已成功将常规战与七天联赛数据备份至 Google Sheet！")
    except Exception as exc:
        print(f"[Google Sheet 备份警告] 同步失败（不影响 GitHub CSV 存档）: {exc}", file=sys.stderr)


if __name__ == "__main__":
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

    if has_error and not war_list and not cwl_list:
        sys.exit(1)
