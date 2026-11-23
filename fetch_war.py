import os
import sys
import urllib.parse
from datetime import datetime, timezone
import pandas as pd
import requests

CLANS = [
    {"name": "萌面打劫", "tag": "#2YR9JVCG8"},
    {"name": "萌虎下山", "tag": "#2JLC9Q8LL"},
    {"name": "小倔强", "tag": "#2CVRYQ9C"},
]

API_TOKEN = os.getenv("COC_API_TOKEN", "").strip()
API_BASE = os.getenv("COC_API_BASE", "https://cocproxy.royaleapi.dev/v1").rstrip("/")
HISTORY_FILE = "war_history.csv"

COLUMNS = [
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


def fetch_current_war(clan_tag: str, token: str) -> dict:
    if not token:
        raise RuntimeError("未检测到 COC_API_TOKEN 环境变量，请先在 GitHub Secrets 中配置。")
    if not clan_tag.startswith("#"):
        clan_tag = "#" + clan_tag
    encoded_tag = urllib.parse.quote(clan_tag)
    url = f"{API_BASE}/clans/{encoded_tag}/currentwar"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    resp = requests.get(url, headers=headers, timeout=20)
    if resp.status_code != 200:
        raise RuntimeError(f"[{clan_tag}] API 请求失败 (HTTP {resp.status_code}): {resp.text}")
    return resp.json()


def parse_war_to_rows(clan_tag: str, default_name: str, data: dict) -> pd.DataFrame:
    state = data.get("state", "notInWar")
    if state not in ("inWar", "warEnded"):
        print(f"[{default_name} {clan_tag}] 当前状态为 {state}，跳过记录。")
        return pd.DataFrame(columns=COLUMNS)

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

    return pd.DataFrame(rows, columns=COLUMNS)


def update_history_csv(all_new_dfs: list, filepath: str = HISTORY_FILE) -> None:
    if os.path.exists(filepath):
        old_df = pd.read_csv(filepath)
        if "clan_tag" not in old_df.columns:
            old_df["clan_tag"] = "#2YR9JVCG8"
    else:
        old_df = pd.DataFrame(columns=COLUMNS)

    valid_dfs = [d for d in all_new_dfs if not d.empty]
    if not valid_dfs:
        if not os.path.exists(filepath):
            old_df.to_csv(filepath, index=False, encoding="utf-8-sig")
        return

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
    print(f"历史战绩库已更新，本次写入 {len(combined_new)} 条成员记录。")


if __name__ == "__main__":
    collected = []
    has_error = False

    for item in CLANS:
        c_name = item["name"]
        c_tag = item["tag"].strip().upper()
        if not c_tag or "第" in c_tag or "TAG" in c_tag:
            print(f"跳过未配置标签的占位部落：{c_name}")
            continue
        if not c_tag.startswith("#"):
            c_tag = "#" + c_tag

        try:
            war_json = fetch_current_war(c_tag, API_TOKEN)
            df_war = parse_war_to_rows(c_tag, c_name, war_json)
            collected.append(df_war)
            if not df_war.empty:
                print(f"[{c_name} {c_tag}] 抓拍成功（状态: {df_war['war_state'].iloc[0]}，{len(df_war)}人）")
        except Exception as exc:
            print(f"[{c_name} {c_tag}] 抓取警告: {exc}", file=sys.stderr)
            has_error = True

    update_history_csv(collected, HISTORY_FILE)
    if has_error and not collected:
        sys.exit(1)
