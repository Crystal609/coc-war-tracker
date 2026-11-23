import os
import sys
import urllib.parse
from datetime import datetime, timezone
import pandas as pd
import requests

CLAN_TAG = os.getenv("COC_CLAN_TAG", "#2YR9JVCG8").strip()
API_TOKEN = os.getenv("COC_API_TOKEN", "").strip()
API_BASE = os.getenv("COC_API_BASE", "https://cocproxy.royaleapi.dev/v1").rstrip("/")
HISTORY_FILE = "war_history.csv"

COLUMNS = [
    "war_id",
    "war_state",
    "start_time",
    "end_time",
    "clan_name",
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
        raise RuntimeError(f"Supercell API 请求失败 (HTTP {resp.status_code}): {resp.text}")
    return resp.json()


def parse_war_to_rows(data: dict) -> pd.DataFrame:
    state = data.get("state", "notInWar")
    if state not in ("inWar", "warEnded"):
        print(f"当前部落战状态为 {state}（非战斗日/已结束状态），跳过记录。")
        return pd.DataFrame(columns=COLUMNS)

    war_id = data.get("preparationStartTime", "")
    start_time = data.get("startTime", "")
    end_time = data.get("endTime", "")
    team_size = int(data.get("teamSize", 0))
    attacks_per_member = int(data.get("attacksPerMember", 2))

    clan = data.get("clan", {})
    opponent = data.get("opponent", {})
    clan_name = clan.get("name", "萌面打劫")
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
            "war_id": war_id,
            "war_state": state,
            "start_time": start_time,
            "end_time": end_time,
            "clan_name": clan_name,
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


def update_history_csv(new_df: pd.DataFrame, filepath: str = HISTORY_FILE) -> None:
    if os.path.exists(filepath):
        old_df = pd.read_csv(filepath)
    else:
        old_df = pd.DataFrame(columns=COLUMNS)

    if new_df.empty:
        if not os.path.exists(filepath):
            old_df.to_csv(filepath, index=False, encoding="utf-8-sig")
        return

    current_war_id = new_df["war_id"].iloc[0]
    if not old_df.empty and "war_id" in old_df.columns:
        old_df = old_df[old_df["war_id"].astype(str) != str(current_war_id)]

    combined = pd.concat([old_df, new_df], ignore_index=True)
    combined = combined.sort_values(by=["war_id", "map_position"], ascending=[True, True])
    combined.to_csv(filepath, index=False, encoding="utf-8-sig")
    print(f"已成功更新场次 {current_war_id}（状态: {new_df['war_state'].iloc[0]}），共 {len(new_df)} 名参战成员。")


if __name__ == "__main__":
    try:
        war_json = fetch_current_war(CLAN_TAG, API_TOKEN)
        df_war = parse_war_to_rows(war_json)
        update_history_csv(df_war, HISTORY_FILE)
    except Exception as exc:
        print(f"执行出错: {exc}", file=sys.stderr)
        sys.exit(1)
