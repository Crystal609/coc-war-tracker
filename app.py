import os
import urllib.parse
from datetime import datetime, timezone
import pandas as pd
import requests
import streamlit as st

st.set_page_config(
    page_title="COC 部落战与联赛战绩追踪",
    page_icon="⚔️",
    layout="wide",
)

# 三个部落配置
CLANS = [
    {"name": "萌面打劫", "tag": "#2YR9JVCG8"},
    {"name": "萌虎下山", "tag": "#2JLC9Q8LL"},
    {"name": "小倔强", "tag": "#2CVRYQ9C"},
]

WAR_HISTORY_FILE = "war_history.csv"
CWL_HISTORY_FILE = "cwl_history.csv"
API_BASE = os.getenv("COC_API_BASE", "https://cocproxy.royaleapi.dev/v1").rstrip("/")


def safe_int(val, default: int = 0) -> int:
    try:
        if pd.isna(val):
            return default
        return int(float(val))
    except Exception:
        return default


def safe_float(val, default: float = 0.0) -> float:
    try:
        if pd.isna(val):
            return default
        return float(val)
    except Exception:
        return default


def normalize_tag(tag: str) -> str:
    t = str(tag or "").strip().upper().replace("O", "0")
    if t and not t.startswith("#"):
        t = "#" + t
    return t


def parse_coc_utc(val: str) -> datetime | None:
    s = str(val or "").strip()
    try:
        if len(s) >= 15 and "T" in s:
            return datetime.strptime(s[:15], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
        if len(s) >= 19 and s[4] == "-":
            return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:
        return None
    return None


def classify_war_status(war_state: str, end_time_str: str) -> str:
    """
    区分三种状态：
    - 'warEnded': 已抓到终局（漏刀 100% 准确）
    - 'inWar': 确实还在战斗中
    - 'unfinalized': 比赛已过结束时间，但最后抓拍停在结束前（未抓到终局，不可误判漏刀）
    """
    st_raw = str(war_state or "").strip()
    if st_raw == "warEnded":
        return "warEnded"
    if st_raw == "inWar":
        end_dt = parse_coc_utc(end_time_str)
        if end_dt is not None and datetime.now(timezone.utc) > end_dt:
            return "unfinalized"
        return "inWar"
    return st_raw


def get_secret(key: str, default: str = "") -> str:
    try:
        if key in st.secrets:
            return str(st.secrets[key]).strip()
    except Exception:
        pass
    return os.getenv(key, default).strip()


def format_month_cn(val: str) -> str:
    """将 '2026-11' 或 '20261122T...' 统一格式化为 '2026 11月'"""
    s = str(val or "").strip()
    if len(s) >= 7 and s[4] == "-":
        return f"{s[:4]} {s[5:7]}月"
    if len(s) >= 6 and s[:6].isdigit():
        return f"{s[:4]} {s[4:6]}月"
    return s


def format_date_str(val: str) -> str:
    """将 '20261122T104100.000Z' 转为 '2026-11-22'"""
    s = str(val or "").strip()
    if len(s) >= 8 and s[:8].isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    if len(s) >= 10 and s[4] == "-":
        return s[:10]
    return s


@st.cache_data(ttl=120)
def load_csv_safe(filepath: str) -> pd.DataFrame:
    if not os.path.exists(filepath):
        return pd.DataFrame()
    try:
        return pd.read_csv(filepath)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=120)
def api_get_cached(path: str, token: str) -> tuple[int, dict | None]:
    if not token:
        return 0, None
    url = f"{API_BASE}{path}"
    try:
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=15,
        )
        if resp.status_code == 200:
            return 200, resp.json()
        return resp.status_code, None
    except Exception:
        return -1, None


def fetch_live_war(clan_tag: str, token: str) -> dict | None:
    enc = urllib.parse.quote(clan_tag)
    code, data = api_get_cached(f"/clans/{enc}/currentwar", token)
    return data if code == 200 else None


def fetch_external_player_live(player_tag: str, token: str) -> dict:
    """实时查询任意玩家档案及其当前所在部落的常规战与七天联赛"""
    clean_tag = normalize_tag(player_tag)
    if not clean_tag or len(clean_tag) < 4:
        return {"error": "请输入有效的玩家标签（例如 #P8QGLU980）。"}
    if not token:
        return {"error": "未配置 COC_API_TOKEN，无法进行实时跨部落接口查询。"}

    enc_p = urllib.parse.quote(clean_tag)
    code, pdata = api_get_cached(f"/players/{enc_p}", token)
    if code == 404 or not pdata:
        return {"error": f"未找到玩家 `{clean_tag}`，请检查标签是否拼写正确（注意数字 0 与字母 O）。"}
    if code != 200:
        return {"error": f"查询失败（HTTP {code}），请稍后重试。"}

    war_hero_stars = 0
    cwl_legend_stars = 0
    for ach in pdata.get("achievements", []) or []:
        aname = ach.get("name", "")
        if aname == "War Hero":
            war_hero_stars = safe_int(ach.get("value", 0))
        elif aname == "War League Legend":
            cwl_legend_stars = safe_int(ach.get("value", 0))

    clan_info = pdata.get("clan") or {}
    cur_clan_tag = clan_info.get("tag", "")
    cur_clan_name = clan_info.get("name", "无部落")

    ext_war_rows = []
    ext_cwl_rows = []
    ext_war_note = ""
    ext_cwl_note = ""

    if cur_clan_tag:
        enc_c = urllib.parse.quote(cur_clan_tag)
        w_code, w_data = api_get_cached(f"/clans/{enc_c}/currentwar", token)
        if w_code == 403:
            ext_war_note = f"该玩家当前所在部落 **{cur_clan_name}** 隐藏了对战日志，无法读取常规战明细。"
        elif w_code == 200 and w_data and w_data.get("state") in ("preparation", "inWar", "warEnded"):
            st_map = {"preparation": "准备日", "inWar": "进行中", "warEnded": "已结束"}
            opp_name = w_data.get("opponent", {}).get("name", "未知对手")
            atk_lim = safe_int(w_data.get("attacksPerMember", 2), 2)
            for m in w_data.get("clan", {}).get("members", []):
                if normalize_tag(m.get("tag", "")) == clean_tag:
                    atks = m.get("attacks", []) or []
                    used = len(atks)
                    ext_war_rows.append({
                        "日期/赛季": f"{format_date_str(w_data.get('startTime', ''))} (当前)",
                        "赛事类型": "常规战",
                        "所属部落": cur_clan_name,
                        "对手部落": opp_name,
                        "顺位": f"#{safe_int(m.get('mapPosition', 0))}",
                        "大本": safe_int(m.get("townhallLevel", 0)),
                        "出刀情况": f"{used} / {atk_lim}",
                        "漏刀标记": f"❌ 漏{max(0, atk_lim - used)}刀" if (w_data.get("state") == "warEnded" and used < atk_lim) else ("⏳ 进行中" if used < atk_lim else "✅ 满刀"),
                        "得星": sum(safe_int(a.get("stars", 0)) for a in atks),
                        "三星数": sum(1 for a in atks if safe_int(a.get("stars", 0)) == 3),
                        "总摧毁(%)": round(sum(safe_float(a.get("destructionPercentage", 0.0)) for a in atks), 1),
                        "状态": st_map.get(w_data.get("state", ""), ""),
                    })

        g_code, g_data = api_get_cached(f"/clans/{enc_c}/currentwar/leaguegroup", token)
        if g_code == 403:
            ext_cwl_note = f"该玩家当前所在部落 **{cur_clan_name}** 隐藏了联赛日志。"
        elif g_code == 200 and g_data and g_data.get("state") != "notInWar":
            season = str(g_data.get("season", ""))
            for r_idx, rnd in enumerate(g_data.get("rounds", []), start=1):
                for w_tag in rnd.get("warTags", []):
                    if not w_tag or w_tag == "#0":
                        continue
                    enc_wt = urllib.parse.quote(w_tag)
                    rw_code, rw_data = api_get_cached(f"/clanwarleagues/wars/{enc_wt}", token)
                    if rw_code != 200 or not rw_data:
                        continue
                    c1 = rw_data.get("clan", {})
                    c2 = rw_data.get("opponent", {})
                    if normalize_tag(c1.get("tag", "")) == cur_clan_tag:
                        our_c, opp_c = c1, c2
                    elif normalize_tag(c2.get("tag", "")) == cur_clan_tag:
                        our_c, opp_c = c2, c1
                    else:
                        continue

                    w_st = rw_data.get("state", "")
                    if w_st in ("inWar", "warEnded"):
                        for m in our_c.get("members", []):
                            if normalize_tag(m.get("tag", "")) == clean_tag:
                                atks = m.get("attacks", []) or []
                                used = len(atks)
                                stars = sum(safe_int(a.get("stars", 0)) for a in atks)
                                dest = sum(safe_float(a.get("destructionPercentage", 0.0)) for a in atks)
                                ext_cwl_rows.append({
                                    "日期/赛季": f"{format_month_cn(season)} · 第{r_idx}天",
                                    "赛事类型": f"七天联赛 D{r_idx}",
                                    "所属部落": cur_clan_name,
                                    "对手部落": opp_c.get("name", "未知对手"),
                                    "顺位": f"#{safe_int(m.get('mapPosition', 0))}",
                                    "大本": safe_int(m.get("townhallLevel", 0)),
                                    "出刀情况": f"{used} / 1",
                                    "漏刀标记": "✅ 满刀" if used > 0 else ("❌ 漏1刀" if w_st == "warEnded" else "⏳ 待出刀"),
                                    "得星": stars,
                                    "三星数": 1 if (used > 0 and stars == 3) else 0,
                                    "总摧毁(%)": round(dest, 1),
                                    "状态": "进行中" if w_st == "inWar" else "已结束",
                                })
                    break

    return {
        "name": pdata.get("name", ""),
        "tag": pdata.get("tag", clean_tag),
        "town_hall": safe_int(pdata.get("townHallLevel", 0)),
        "exp_level": safe_int(pdata.get("expLevel", 0)),
        "clan_name": cur_clan_name,
        "clan_tag": cur_clan_tag,
        "war_pref": "参战 (绿牌)" if pdata.get("warPreference") == "in" else "免战 (红牌)",
        "war_stars_total": safe_int(pdata.get("warStars", 0)),
        "war_hero_stars": war_hero_stars,
        "cwl_legend_stars": cwl_legend_stars,
        "ext_war_rows": ext_war_rows,
        "ext_cwl_rows": ext_cwl_rows,
        "ext_war_note": ext_war_note,
        "ext_cwl_note": ext_cwl_note,
    }


header_col1, header_col2 = st.columns([4, 1])
with header_col1:
    st.title("⚔️ COC 部落战与联赛数据中心")
with header_col2:
    st.write("")
    if st.button("🔄 刷新最新数据", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

war_df = load_csv_safe(WAR_HISTORY_FILE)
cwl_df = load_csv_safe(CWL_HISTORY_FILE)

tab_live, tab_war, tab_cwl, tab_member = st.tabs(
    ["⚔️ 实时部落战", "📊 常规战归档", "🏆 七天联赛", "👤 成员战绩查询"]
)

# ==========================================
# Tab 1: 实时部落战
# ==========================================
with tab_live:
    api_token = get_secret("COC_API_TOKEN")
    selected_clan_live = st.selectbox(
        "选择查看部落",
        options=[f"{c['name']} ({c['tag']})" for c in CLANS],
        key="live_clan_select",
    )
    clan_obj_live = CLANS[[f"{c['name']} ({c['tag']})" for c in CLANS].index(selected_clan_live)]

    if not api_token:
        st.info("未检测到 `COC_API_TOKEN`，当前仅展示下方归档标签页中的历史数据；如需实时刷新，请在 Streamlit Secrets 中添加 `COC_API_TOKEN`。")
    else:
        live_data = fetch_live_war(clan_obj_live["tag"], api_token)
        if not live_data or live_data.get("state") == "notInWar":
            st.warning(f"**{clan_obj_live['name']}** 当前未处于常规部落战中（或处于七天联赛期间，请切换至「🏆 七天联赛」查看）。")
        else:
            state_map = {
                "preparation": "⏳ 准备日",
                "inWar": "🔥 战斗日进行中",
                "warEnded": "🏁 已结束",
            }
            st.subheader(
                f"{live_data.get('clan', {}).get('name', clan_obj_live['name'])} 🆚 "
                f"{live_data.get('opponent', {}).get('name', '未知对手')}（{state_map.get(live_data.get('state', ''), live_data.get('state', ''))}）"
            )
            c1_info = live_data.get("clan", {})
            c2_info = live_data.get("opponent", {})
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("我方得星", f"{c1_info.get('stars', 0)} ★")
            m2.metric("敌方得星", f"{c2_info.get('stars', 0)} ★")
            m3.metric("我方摧毁率", f"{c1_info.get('destructionPercentage', 0):.1f}%")
            m4.metric("已出刀数", f"{c1_info.get('attacks', 0)} / {live_data.get('teamSize', 0) * live_data.get('attacksPerMember', 2)}")

            atk_limit = safe_int(live_data.get("attacksPerMember", 2), 2)
            live_rows = []
            for m in c1_info.get("members", []):
                atks = m.get("attacks", []) or []
                used = len(atks)
                live_rows.append({
                    "顺位": safe_int(m.get("mapPosition", 0)),
                    "大本": safe_int(m.get("townhallLevel", 0)),
                    "成员名称": m.get("name", ""),
                    "玩家标签": m.get("tag", ""),
                    "已出刀": used,
                    "剩余刀": max(0, atk_limit - used),
                    "得星": sum(safe_int(a.get("stars", 0)) for a in atks),
                    "总摧毁(%)": round(sum(safe_float(a.get("destructionPercentage", 0.0)) for a in atks), 1),
                })
            if live_rows:
                df_live_show = pd.DataFrame(live_rows).sort_values("顺位")
                st.dataframe(df_live_show, use_container_width=True, hide_index=True)

# ==========================================
# Tab 2: 常规战归档（仅 warEnded 计入漏刀；未抓到终局的快照不误判漏刀）
# ==========================================
with tab_war:
    if war_df.empty:
        st.info("暂无常规战归档记录，等待 GitHub Actions 自动抓拍后即可查看。")
    else:
        col_w1, col_w2 = st.columns(2)
        with col_w1:
            clan_opts_w = ["全部部落"] + [f"{c['name']} ({c['tag']})" for c in CLANS]
            sel_w_clan = st.selectbox("筛选部落", clan_opts_w, key="war_arch_clan")

        range_map = {
            "近 5 场": 5,
            "近 10 场": 10,
            "近 15 场": 15,
            "近 30 场": 30,
            "近 50 场": 50,
            "全部已归档场次": None,
        }
        with col_w2:
            sel_range_label = st.selectbox(
                "统计场次范围",
                options=list(range_map.keys()),
                index=2,
                key="war_range_select",
            )

        sub_war = war_df.copy()
        if sel_w_clan != "全部部落":
            target_tag = sel_w_clan.split("(")[-1].rstrip(")")
            sub_war = sub_war[sub_war["clan_tag"].astype(str) == target_tag]

        sub_war["real_status"] = sub_war.apply(
            lambda r: classify_war_status(r.get("war_state", ""), r.get("end_time", "")),
            axis=1,
        )
        sub_war["confirmed_missed"] = sub_war.apply(
            lambda r: safe_int(r.get("attacks_missed", 0)) if r["real_status"] == "warEnded" else 0,
            axis=1,
        )
        sub_war["confirmed_expected"] = sub_war.apply(
            lambda r: safe_int(r.get("attacks_per_member", 2), 2) if r["real_status"] == "warEnded" else safe_int(r.get("attacks_used", 0)),
            axis=1,
        )

        total_wars_cnt = int(sub_war["war_id"].astype(str).nunique())
        unfinalized_cnt = int(sub_war[sub_war["real_status"] == "unfinalized"]["war_id"].astype(str).nunique())
        target_n = range_map[sel_range_label]

        if target_n is None:
            sub_war_recent = sub_war.copy()
        else:
            kept_parts = []
            for _, grp_clan in sub_war.groupby("clan_tag"):
                c_wars = sorted(grp_clan["war_id"].astype(str).unique().tolist())[-target_n:]
                kept_parts.append(grp_clan[grp_clan["war_id"].astype(str).isin(c_wars)])
            sub_war_recent = pd.concat(kept_parts, ignore_index=True) if kept_parts else sub_war.copy()

        if unfinalized_cnt > 0:
            st.caption(
                f"ℹ️ 提示：早期有 {unfinalized_cnt} 场对战在结束前数小时抓拍后未抓到终局快照（已自动免除漏刀判定，防止最后几小时压哨出刀被误算为漏刀）。"
            )

        if not sub_war_recent.empty:
            summary_w = (
                sub_war_recent.groupby(["clan_name", "player_tag", "player_name"], as_index=False)
                .agg(
                    大本=("town_hall", "max"),
                    参战场次=("war_id", "nunique"),
                    已核算刀数=("confirmed_expected", "sum"),
                    实出刀=("attacks_used", "sum"),
                    确认漏刀=("confirmed_missed", "sum"),
                    总星=("total_stars", "sum"),
                    三星数=("three_stars", "sum"),
                )
            )
            summary_w["漏刀率(%)"] = (
                summary_w["确认漏刀"] / summary_w["已核算刀数"].replace(0, 1) * 100
            ).round(1)
            summary_w = summary_w.sort_values(
                by=["确认漏刀", "漏刀率(%)", "总星"], ascending=[False, False, False]
            )
            summary_w = summary_w.rename(
                columns={
                    "clan_name": "所属部落",
                    "player_tag": "玩家标签",
                    "player_name": "成员名称",
                }
            )
            st.subheader(f"{sel_range_label}常规战考勤汇总（当前共 {total_wars_cnt} 场）")
            st.dataframe(summary_w, use_container_width=True, hide_index=True)

            with st.expander("查看逐场原始出刀明细", expanded=False):
                detail_w = sub_war_recent.copy()
                detail_w["日期"] = detail_w["start_time"].apply(format_date_str)
                status_cn_map = {
                    "warEnded": "✅ 已结束(终局)",
                    "inWar": "🔥 进行中",
                    "unfinalized": "⚠️ 未抓到终局(不计漏刀)",
                    "preparation": "⏳ 准备日",
                }
                detail_w["抓拍状态"] = detail_w["real_status"].map(status_cn_map).fillna(detail_w["war_state"])
                detail_w = detail_w.rename(
                    columns={
                        "clan_name": "所属部落",
                        "opponent_name": "对手部落",
                        "map_position": "顺位",
                        "player_name": "成员名称",
                        "player_tag": "玩家标签",
                        "town_hall": "大本",
                        "attacks_used": "实出刀",
                        "confirmed_missed": "确认漏刀",
                        "total_stars": "得星",
                        "three_stars": "三星数",
                        "total_destruction": "总摧毁(%)",
                    }
                )
                cols_show = [
                    "日期", "所属部落", "对手部落", "顺位",
                    "成员名称", "玩家标签", "大本", "实出刀",
                    "确认漏刀", "得星", "三星数", "总摧毁(%)", "抓拍状态"
                ]
                cols_show = [c for c in cols_show if c in detail_w.columns]
                st.dataframe(
                    detail_w.sort_values(by=["war_id", "clan_tag", "顺位"], ascending=[False, True, True])[cols_show],
                    use_container_width=True,
                    hide_index=True,
                )

# ==========================================
# Tab 3: 七天联赛
# ==========================================
with tab_cwl:
    if cwl_df.empty:
        st.info("暂无七天联赛归档记录，联赛开打后系统每 30 分钟会自动抓拍保存。")
    else:
        cwl_work = cwl_df.copy()
        cwl_work["season_label"] = cwl_work["season"].apply(format_month_cn)

        col_c1, col_c2 = st.columns(2)
        with col_c1:
            seasons_raw = sorted(cwl_work["season"].astype(str).unique().tolist(), reverse=True)
            season_map = {format_month_cn(s): s for s in seasons_raw}
            sel_season_label = st.selectbox("选择联赛赛季", list(season_map.keys()), key="cwl_season_sel")
            sel_season_raw = season_map[sel_season_label]
        with col_c2:
            clan_opts_c = ["全部部落"] + [f"{c['name']} ({c['tag']})" for c in CLANS]
            sel_c_clan = st.selectbox("选择部落", clan_opts_c, key="cwl_clan_sel")

        sub_cwl = cwl_work[cwl_work["season"].astype(str) == sel_season_raw]
        if sel_c_clan != "全部部落":
            t_tag = sel_c_clan.split("(")[-1].rstrip(")")
            sub_cwl = sub_cwl[sub_cwl["clan_tag"].astype(str) == t_tag]

        if sub_cwl.empty:
            st.warning("该筛选条件下暂无联赛数据。")
        else:
            matrix_rows = []
            for (ctag, cname), grp_c in sub_cwl.groupby(["clan_tag", "clan_name"]):
                players_c = (
                    grp_c.groupby(["player_tag", "player_name"], as_index=False)
                    .agg(
                        大本=("town_hall", "max"),
                        上场天数=("round_num", "nunique"),
                        已出刀=("attacks_used", "sum"),
                        漏打=("attacks_missed", "sum"),
                        总得星=("stars", "sum"),
                    )
                )
                day_dict = {}
                for _, r in grp_c.iterrows():
                    k = (r["player_tag"], safe_int(r["round_num"]))
                    if safe_int(r["attacks_used"]) > 0:
                        day_dict[k] = f"{safe_int(r['stars'])}★"
                    elif str(r["war_state"]) == "warEnded":
                        day_dict[k] = "❌漏"
                    else:
                        day_dict[k] = "⏳待"

                for _, p in players_c.iterrows():
                    pt = p["player_tag"]
                    row_m = {
                        "部落": cname,
                        "成员名称": p["player_name"],
                        "玩家标签": pt,
                        "大本": safe_int(p["大本"]),
                        "上场": safe_int(p["上场天数"]),
                        "已出刀": safe_int(p["已出刀"]),
                        "漏打": safe_int(p["漏打"]),
                        "总星": safe_int(p["总得星"]),
                        "满8星": "✅是" if safe_int(p["总得星"]) >= 8 else "未满",
                    }
                    for d in range(1, 8):
                        row_m[f"DAY {d}"] = day_dict.get((pt, d), "—")
                    matrix_rows.append(row_m)

            df_matrix = pd.DataFrame(matrix_rows).sort_values(
                by=["漏打", "总星"], ascending=[False, False]
            )
            st.subheader(f"🏆 {sel_season_label} 七天联赛战绩总览")
            st.dataframe(df_matrix, use_container_width=True, hide_index=True)

            with st.expander("查看每日对阵原始明细", expanded=False):
                st.dataframe(
                    sub_cwl.sort_values(by=["clan_tag", "round_num", "map_position"]),
                    use_container_width=True,
                    hide_index=True,
                )

# ==========================================
# Tab 4: 👤 成员战绩查询
# ==========================================
with tab_member:
    search_mode = st.radio(
        "查询方式",
        options=["📋 从本群归档成员中选择", "🔍 输入任意 #玩家标签 跨部落搜索（含外部部落）"],
        horizontal=True,
        key="member_search_mode",
    )

    all_records = []
    if not war_df.empty:
        for _, r in war_df.iterrows():
            used = safe_int(r.get("attacks_used", 0))
            limit = safe_int(r.get("attacks_per_member", 2), 2)
            missed = safe_int(r.get("attacks_missed", max(0, limit - used)))
            stars = safe_int(r.get("total_stars", 0))
            s3 = safe_int(r.get("three_stars", 0))
            dest = safe_float(r.get("total_destruction", 0.0))
            real_st = classify_war_status(r.get("war_state", ""), r.get("end_time", ""))
            st_cn = {
                "warEnded": "已结束",
                "inWar": "进行中",
                "unfinalized": "未抓到终局",
                "preparation": "准备日",
            }.get(real_st, real_st)

            all_records.append({
                "sort_key": str(r.get("start_time", "")) or str(r.get("war_id", "")),
                "日期/赛季": f"{format_date_str(r.get('start_time', ''))} ({format_month_cn(r.get('start_time', ''))})",
                "赛事类型": "常规战",
                "所属部落": str(r.get("clan_name", "")),
                "clan_tag": str(r.get("clan_tag", "")),
                "对手部落": str(r.get("opponent_name", "")),
                "player_tag": normalize_tag(r.get("player_tag", "")),
                "player_name": str(r.get("player_name", "")),
                "大本": safe_int(r.get("town_hall", 0)),
                "顺位": f"#{safe_int(r.get('map_position', 0))}",
                "已出刀": used,
                "应出刀": limit if real_st == "warEnded" else used,
                "出刀情况": f"{used} / {limit}",
                "漏刀": missed if real_st == "warEnded" else 0,
                "得星": stars,
                "三星数": s3,
                "总摧毁(%)": round(dest, 1),
                "平均摧毁(%)": round(dest / used, 1) if used > 0 else 0.0,
                "状态": st_cn,
            })

    if not cwl_df.empty:
        for _, r in cwl_df.iterrows():
            used = safe_int(r.get("attacks_used", 0))
            missed = safe_int(r.get("attacks_missed", max(0, 1 - used)))
            stars = safe_int(r.get("stars", 0))
            s3 = 1 if (used > 0 and stars == 3) else 0
            dest = safe_float(r.get("destruction", 0.0))
            rn = safe_int(r.get("round_num", 0))
            sn = str(r.get("season", ""))
            st_raw = str(r.get("war_state", ""))
            st_label = "进行中" if st_raw == "inWar" else ("已结束" if st_raw == "warEnded" else st_raw)

            all_records.append({
                "sort_key": f"{sn}-D{rn:02d}",
                "日期/赛季": f"{format_month_cn(sn)} · 第{rn}天",
                "赛事类型": f"七天联赛 D{rn}",
                "所属部落": str(r.get("clan_name", "")),
                "clan_tag": str(r.get("clan_tag", "")),
                "对手部落": str(r.get("opponent_name", "")),
                "player_tag": normalize_tag(r.get("player_tag", "")),
                "player_name": str(r.get("player_name", "")),
                "大本": safe_int(r.get("town_hall", 0)),
                "顺位": f"#{safe_int(r.get('map_position', 0))}",
                "已出刀": used,
                "应出刀": 1 if st_raw == "warEnded" else used,
                "出刀情况": f"{used} / 1",
                "漏刀": missed if st_raw == "warEnded" else 0,
                "得星": stars,
                "三星数": s3,
                "总摧毁(%)": round(dest, 1),
                "平均摧毁(%)": round(dest, 1) if used > 0 else 0.0,
                "状态": st_label,
            })

    df_all_m = pd.DataFrame(all_records) if all_records else pd.DataFrame()

    if search_mode.startswith("📋"):
        if df_all_m.empty:
            st.info("暂无成员战绩数据，等首次抓拍写入后即可在此查询任意成员的近期表现。")
        else:
            f_col1, f_col2, f_col3 = st.columns([1.3, 2.2, 1.5])
            with f_col1:
                m_clan_opts = ["全部部落"] + [f"{c['name']} ({c['tag']})" for c in CLANS]
                sel_m_clan = st.selectbox("1. 筛选部落", m_clan_opts, key="member_clan_filter")

            df_filtered_clan = df_all_m.copy()
            if sel_m_clan != "全部部落":
                m_ctag = sel_m_clan.split("(")[-1].rstrip(")")
                df_filtered_clan = df_filtered_clan[df_filtered_clan["clan_tag"] == m_ctag]

            latest_players = (
                df_filtered_clan.sort_values("sort_key", ascending=False)
                .drop_duplicates(subset=["player_tag"])
            )
            player_options = []
            tag_lookup = {}
            for _, pr in latest_players.iterrows():
                label = f"{pr['player_name']} ({pr['player_tag']}) · {pr['所属部落']} · {pr['大本']}本"
                player_options.append(label)
                tag_lookup[label] = pr["player_tag"]

            with f_col2:
                if not player_options:
                    st.warning("当前筛选部落下暂无成员记录。")
                    sel_player_label = None
                else:
                    sel_player_label = st.selectbox(
                        "2. 选择成员（可直接输入名字搜索）",
                        options=player_options,
                        key="member_player_select",
                    )

            with f_col3:
                mode_filter = st.selectbox(
                    "3. 赛事范围",
                    options=["全部战绩 (常规+联赛)", "仅常规战", "仅七天联赛"],
                    key="member_mode_filter",
                )

            if sel_player_label:
                chosen_tag = tag_lookup[sel_player_label]
                p_df = df_all_m[df_all_m["player_tag"] == chosen_tag].copy()

                if mode_filter == "仅常规战":
                    p_df = p_df[p_df["赛事类型"] == "常规战"]
                elif mode_filter == "仅七天联赛":
                    p_df = p_df[p_df["赛事类型"].str.startswith("七天联赛")]

                p_df = p_df.sort_values("sort_key", ascending=False)

                if p_df.empty:
                    st.warning("该成员在所选赛事类型下暂无记录。")
                else:
                    max_rec = len(p_df)
                    recent_k = (
                        st.slider(
                            "查看最近场次数量",
                            min_value=1,
                            max_value=max_rec,
                            value=min(15, max_rec),
                            key="member_recent_k_slider",
                        )
                        if max_rec > 1
                        else 1
                    )
                    p_recent = p_df.head(recent_k).copy()

                    total_matches = len(p_recent)
                    total_used = int(p_recent["已出刀"].sum())
                    total_limit = int(p_recent["应出刀"].sum())
                    total_missed = int(p_recent["漏刀"].sum())
                    total_stars = int(p_recent["得星"].sum())
                    total_3s = int(p_recent["三星数"].sum())
                    avg_stars = round(total_stars / total_used, 2) if total_used > 0 else 0.0
                    rate_3s = round(total_3s / total_used * 100, 1) if total_used > 0 else 0.0
                    avg_dest = round(p_recent[p_recent["已出刀"] > 0]["平均摧毁(%)"].mean(), 1) if total_used > 0 else 0.0

                    k1, k2, k3, k4, k5 = st.columns(5)
                    k1.metric("近期参战", f"{total_matches} 场")
                    k2.metric(
                        "出刀 / 漏刀",
                        f"{total_used} / {total_limit} 刀",
                        delta=f"漏 {total_missed} 刀" if total_missed > 0 else "全勤零漏刀",
                        delta_color="inverse" if total_missed > 0 else "normal",
                    )
                    k3.metric("累计得星", f"{total_stars} ★", delta=f"刀均 {avg_stars} ★")
                    k4.metric("三星次数", f"{total_3s} 次", delta=f"三星率 {rate_3s}%")
                    k5.metric("刀均摧毁率", f"{avg_dest}%")

                    def fmt_miss(row):
                        if row["状态"] == "进行中":
                            return "⏳ 进行中"
                        if row["状态"] == "未抓到终局":
                            return "⚠️ 未抓到终局"
                        return f"❌ 漏{int(row['漏刀'])}刀" if int(row["漏刀"]) > 0 else "✅ 满刀"

                    p_recent["漏刀标记"] = p_recent.apply(fmt_miss, axis=1)
                    display_cols = [
                        "日期/赛季",
                        "赛事类型",
                        "所属部落",
                        "对手部落",
                        "顺位",
                        "大本",
                        "出刀情况",
                        "漏刀标记",
                        "得星",
                        "三星数",
                        "总摧毁(%)",
                        "状态",
                    ]
                    st.subheader(f"📋 {p_recent.iloc[0]['player_name']} 最近 {total_matches} 场战绩明细")
                    st.dataframe(p_recent[display_cols], use_container_width=True, hide_index=True)

    else:
        sc1, sc2 = st.columns([3, 1])
        with sc1:
            input_tag = st.text_input(
                "输入玩家标签（支持不带 #，例如 P8QGLU980）",
                placeholder="#XXXXXXXXX",
                key="ext_player_tag_input",
            )
        with sc2:
            st.write("")
            st.write("")
            do_search = st.button("🔍 立即查询", use_container_width=True)

        if input_tag.strip() or do_search:
            norm_t = normalize_tag(input_tag)
            token_live = get_secret("COC_API_TOKEN")
            res = fetch_external_player_live(norm_t, token_live)

            if "error" in res:
                st.error(res["error"])
            else:
                st.subheader(f"👤 {res['name']} ({res['tag']}) · {res['town_hall']}本 · 当前部落：{res['clan_name']}")
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("当前所在部落", res["clan_name"], delta=res["clan_tag"] or "未加入部落")
                m2.metric("生涯七天联赛总星", f"{res['cwl_legend_stars']} ★")
                m3.metric("生涯常规战总星", f"{res['war_hero_stars']} ★")
                m4.metric("当前参战意愿", res["war_pref"])

                if res["ext_cwl_note"]:
                    st.info(res["ext_cwl_note"])
                if res["ext_war_note"]:
                    st.info(res["ext_war_note"])

                live_ext_list = res["ext_cwl_rows"] + res["ext_war_rows"]
                if live_ext_list:
                    st.markdown("#### 🔥 当前所在部落实时战况（本赛季联赛 / 进行中常规战）")
                    st.dataframe(pd.DataFrame(live_ext_list), use_container_width=True, hide_index=True)

                if not df_all_m.empty:
                    local_hist = df_all_m[df_all_m["player_tag"] == res["tag"]].sort_values("sort_key", ascending=False)
                    if not local_hist.empty:
                        local_hist = local_hist.copy()
                        local_hist["漏刀标记"] = local_hist.apply(
                            lambda r: (
                                "⏳ 进行中" if r["状态"] == "进行中"
                                else ("⚠️ 未抓到终局" if r["状态"] == "未抓到终局"
                                      else (f"❌ 漏{int(r['漏刀'])}刀" if int(r["漏刀"]) > 0 else "✅ 满刀"))
                            ),
                            axis=1,
                        )
                        disp_c = [
                            "日期/赛季", "赛事类型", "所属部落", "对手部落", "顺位",
                            "大本", "出刀情况", "漏刀标记", "得星", "三星数", "总摧毁(%)", "状态"
                        ]
                        st.markdown(f"#### 📂 在本群（萌面打劫 / 萌虎下山 / 小倔强）的历史归档（共 {len(local_hist)} 场）")
                        st.dataframe(local_hist[disp_c], use_container_width=True, hide_index=True)
