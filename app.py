import io
import os
import re
import urllib.parse
from datetime import datetime, timezone
import pandas as pd
import requests
import streamlit as st
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

st.set_page_config(
    page_title="部落战监控台 | 三部落联动",
    page_icon="⚔️",
    layout="centered",
    initial_sidebar_state="collapsed",
)

CLANS = [
    {"name": "萌面打劫", "tag": "#2YR9JVCG8"},
    {"name": "萌虎下山", "tag": "#2JLC9Q8LL"},
    {"name": "小倔强", "tag": "#2CVRYQ9C"},
]

API_BASE = "https://cocproxy.royaleapi.dev/v1"
WAR_HISTORY_FILE = "war_history.csv"
CWL_HISTORY_FILE = "cwl_history.csv"

st.markdown(
    """
    <style>
    .block-container {
        padding-top: 3.4rem !important;
        padding-bottom: 2.2rem !important;
        padding-left: 0.9rem !important;
        padding-right: 0.9rem !important;
        max-width: 860px;
    }
    div[data-testid="stRadio"] > div {
        background: #f1f5f9;
        padding: 6px 10px;
        border-radius: 10px;
        border: 1px solid #cbd5e1;
        gap: 12px;
    }
    .clan-header {
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
        color: #ffffff;
        padding: 13px 16px;
        border-radius: 12px;
        margin-top: 6px;
        margin-bottom: 12px;
        box-shadow: 0 2px 8px rgba(15, 23, 42, 0.12);
    }
    .clan-title {
        font-size: 1.18rem;
        font-weight: 700;
        line-height: 1.35;
        margin: 0;
        word-break: break-word;
    }
    .clan-sub {
        font-size: 0.78rem;
        color: #cbd5e1;
        margin-top: 3px;
    }
    .kpi-grid {
        display: grid;
        grid-template-columns: repeat(2, 1fr);
        gap: 8px;
        margin-bottom: 12px;
    }
    @media (min-width: 640px) {
        .kpi-grid {
            grid-template-columns: repeat(4, 1fr);
        }
    }
    .kpi-card {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 9px 12px;
    }
    .kpi-card.alert {
        background: #fef2f2;
        border-color: #fecaca;
    }
    .kpi-card.ok {
        background: #f0fdf4;
        border-color: #bbf7d0;
    }
    .kpi-label {
        font-size: 0.75rem;
        color: #64748b;
        margin-bottom: 2px;
    }
    .kpi-val {
        font-size: 1.12rem;
        font-weight: 700;
        color: #0f172a;
    }
    .kpi-card.alert .kpi-val {
        color: #b91c1c;
    }
    .kpi-card.ok .kpi-val {
        color: #15803d;
    }
    button[data-baseweb="tab"] {
        font-size: 0.9rem !important;
        padding-left: 10px !important;
        padding-right: 10px !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def render_kpi_grid(items):
    cards_html = ['<div class="kpi-grid">']
    for label, val, stype in items:
        cls = f"kpi-card {stype}".strip()
        cards_html.append(
            f'<div class="{cls}"><div class="kpi-label">{label}</div><div class="kpi-val">{val}</div></div>'
        )
    cards_html.append("</div>")
    st.markdown("".join(cards_html), unsafe_allow_html=True)


def get_secret_val(key_name: str) -> str:
    try:
        if key_name in st.secrets:
            return str(st.secrets[key_name]).strip()
    except Exception:
        pass
    return os.getenv(key_name, "").strip()


def parse_coc_time(ts: str):
    if not ts:
        return None
    try:
        return datetime.strptime(ts, "%Y%m%dT%H%M%S.%fZ").replace(tzinfo=timezone.utc)
    except Exception:
        return None


@st.cache_data(ttl=60)
def fetch_api_json(path: str, token: str) -> dict | None:
    url = f"{API_BASE}{path}"
    resp = requests.get(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=15,
    )
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        raise RuntimeError(f"API 请求失败 ({resp.status_code}): {resp.text}")
    return resp.json()


@st.cache_data(ttl=120)
def fetch_live_cwl_rows(clan_tag: str, clan_name: str, token: str) -> pd.DataFrame:
    encoded = urllib.parse.quote(clan_tag)
    group = fetch_api_json(f"/clans/{encoded}/currentwar/leaguegroup", token)
    if not group or group.get("state") == "notInWar":
        return pd.DataFrame()

    season = str(group.get("season", datetime.now(timezone.utc).strftime("%Y-%m")))
    rounds = group.get("rounds", [])
    rows = []

    for r_idx, rnd in enumerate(rounds, start=1):
        for w_tag in rnd.get("warTags", []):
            if not w_tag or w_tag == "#0":
                continue
            w_data = fetch_api_json(f"/clanwarleagues/wars/{urllib.parse.quote(w_tag)}", token)
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

            for m in our_clan.get("members", []):
                atks = m.get("attacks", []) or []
                used = len(atks)
                missed = max(0, 1 - used)
                stars = sum(int(a.get("stars", 0)) for a in atks)
                dest = sum(float(a.get("destructionPercentage", 0.0)) for a in atks)
                rows.append({
                    "clan_tag": clan_tag,
                    "clan_name": our_clan.get("name", clan_name),
                    "season": season,
                    "round_num": r_idx,
                    "war_tag": w_tag,
                    "war_state": w_state,
                    "opponent_name": opp_clan.get("name", "未知对手"),
                    "team_size": int(w_data.get("teamSize", 15)),
                    "player_tag": m.get("tag", ""),
                    "player_name": m.get("name", ""),
                    "town_hall": int(m.get("townhallLevel", 0)),
                    "map_position": int(m.get("mapPosition", 0)),
                    "attacks_used": used,
                    "attacks_missed": missed,
                    "stars": stars,
                    "destruction": round(dest, 1),
                })
            break

    return pd.DataFrame(rows)


def build_excel_bytes(df: pd.DataFrame, sheet_title: str = "统计表") -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_title

    navy_fill = PatternFill(start_color="1F3864", end_color="1F3864", fill_type="solid")
    severe_fill = PatternFill(start_color="FADBD8", end_color="FADBD8", fill_type="solid")
    minor_fill = PatternFill(start_color="FCF3CF", end_color="FCF3CF", fill_type="solid")
    ok_fill = PatternFill(start_color="E8F8F5", end_color="E8F8F5", fill_type="solid")
    zebra_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
    white_fill = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")

    font_header = Font(name="Microsoft YaHei", size=10, bold=True, color="FFFFFF")
    font_data = Font(name="Microsoft YaHei", size=10, color="1E293B")
    font_severe = Font(name="Microsoft YaHei", size=10, bold=True, color="922B21")
    font_minor = Font(name="Microsoft YaHei", size=10, bold=True, color="7D6608")
    font_ok = Font(name="Microsoft YaHei", size=10, bold=True, color="117864")

    thin = Side(style="thin", color="D0D7DE")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    cols = list(df.columns)
    for c_idx, col_name in enumerate(cols, start=1):
        cell = ws.cell(row=1, column=c_idx, value=col_name)
        cell.fill = navy_fill
        cell.font = font_header
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border
    ws.row_dimensions[1].height = 26

    for r_idx, row in df.iterrows():
        excel_r = r_idx + 2
        status_val = str(row.get("状态", ""))
        is_severe = "严重" in status_val or "0刀" in status_val or "漏" in status_val
        is_minor = "差1刀" in status_val or "未满8星" in status_val

        row_fill = severe_fill if is_severe else (minor_fill if is_minor else (zebra_fill if r_idx % 2 == 1 else white_fill))
        row_font = font_severe if is_severe else (font_minor if is_minor else font_data)

        for c_idx, col_name in enumerate(cols, start=1):
            val = row[col_name]
            cell = ws.cell(row=excel_r, column=c_idx, value=val)
            cell.fill = row_fill
            cell.font = row_font
            cell.border = border
            cell.alignment = Alignment(horizontal="left" if "成员" in col_name else "center", vertical="center")
            if col_name == "状态" and not is_severe and not is_minor:
                cell.fill = ok_fill
                cell.font = font_ok
        ws.row_dimensions[excel_r].height = 21

    for c_idx in range(1, len(cols) + 1):
        ws.column_dimensions[get_column_letter(c_idx)].width = 12
    ws.freeze_panes = "C2"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ==================== 顶部一键切换部落 ====================
clan_names = [c["name"] for c in CLANS]
selected_name = st.radio(
    "🏰 点击切换部落：",
    options=clan_names,
    horizontal=True,
)
selected_clan = next(c for c in CLANS if c["name"] == selected_name)
ACTIVE_NAME = selected_clan["name"]
ACTIVE_TAG = selected_clan["tag"].strip().upper()
BACKUP_SHEET_ID = get_secret_val("GOOGLE_SHEET_ID")

header_extra = ""
if BACKUP_SHEET_ID:
    sheet_url = f"https://docs.google.com/spreadsheets/d/{BACKUP_SHEET_ID}/edit"
    header_extra = f' · <a href="{sheet_url}" target="_blank" style="color:#38bdf8;text-decoration:none;">📊 打开云端Sheet备份</a>'

st.markdown(
    f"""
    <div class="clan-header">
        <div class="clan-title">⚔️ {ACTIVE_NAME} ({ACTIVE_TAG})</div>
        <div class="clan-sub">每30分钟全自动抓拍归档 · 三部落独立统计{header_extra}</div>
    </div>
    """,
    unsafe_allow_html=True,
)

tab_live, tab_history, tab_cwl = st.tabs([
    "🔴 实时催刀",
    "📊 常规战归档",
    "🏆 七天联赛",
])

with tab_live:
    token = get_secret_val("COC_API_TOKEN")
    if not token:
        st.warning("尚未检测到 `COC_API_TOKEN`，请在 Streamlit App 设置的 Secrets 中填入官方 Token。")
    else:
        if st.button("🔄 刷新实时战况", use_container_width=True):
            st.cache_data.clear()

        try:
            encoded_tag = urllib.parse.quote(ACTIVE_TAG)
            war = fetch_api_json(f"/clans/{encoded_tag}/currentwar", token) or {}
            state = war.get("state", "notInWar")
            state_map = {
                "notInWar": "⚪ 当前未开战",
                "preparation": "🟡 备战日（准备中）",
                "inWar": "🔴 战斗日进行中",
                "warEnded": "🏁 本场已结束（结算中）",
            }
            st.markdown(f"**当前状态：{state_map.get(state, state)}**")

            if state == "notInWar":
                st.info(f"**{ACTIVE_NAME}** 目前没有正在进行的常规部落战。如果在打月度联赛，请点右侧「🏆 七天联赛」查看。")
            else:
                clan_info = war.get("clan", {})
                opp_info = war.get("opponent", {})
                team_size = war.get("teamSize", 0)
                atk_limit = war.get("attacksPerMember", 2)

                end_dt = parse_coc_time(war.get("endTime", ""))
                remain_str = "-"
                if end_dt:
                    diff = end_dt - datetime.now(timezone.utc)
                    if diff.total_seconds() > 0:
                        hrs = int(diff.total_seconds() // 3600)
                        mins = int((diff.total_seconds() % 3600) // 60)
                        remain_str = f"{hrs}h {mins}m"
                    else:
                        remain_str = "已结束"

                render_kpi_grid([
                    ("对战规模", f"{team_size} vs {team_size}", ""),
                    ("剩余时间", remain_str, "alert" if state == "inWar" else ""),
                    ("我方总星", f"{clan_info.get('stars', 0)} ★ ({clan_info.get('destructionPercentage', 0):.1f}%)", "ok"),
                    ("敌方总星", f"{opp_info.get('stars', 0)} ★ ({opp_info.get('destructionPercentage', 0):.1f}%)", ""),
                ])

                members = clan_info.get("members", [])
                live_rows = []
                for m in sorted(members, key=lambda x: x.get("mapPosition", 999)):
                    atks = m.get("attacks", []) or []
                    used = len(atks)
                    rem = max(0, atk_limit - used)
                    stars = sum(int(a.get("stars", 0)) for a in atks)
                    if rem == atk_limit:
                        st_label = "🔴 0刀"
                    elif rem > 0:
                        st_label = f"🟡 差{rem}刀"
                    else:
                        st_label = "🟢 已满"

                    live_rows.append({
                        "状态": st_label,
                        "位次": f"#{m.get('mapPosition', 0)}",
                        "成员名称": m.get("name", ""),
                        "出刀": f"{used}/{atk_limit}",
                        "剩余": rem,
                        "得星": stars,
                    })

                live_df = pd.DataFrame(live_rows)
                live_df = live_df.sort_values(by=["剩余", "位次"], ascending=[False, True]).reset_index(drop=True)

                only_rem = st.checkbox("仅看还没打满的成员", value=False, key="live_only_rem")
                show_live = live_df[live_df["剩余"] > 0] if only_rem else live_df

                def style_live(r):
                    s = str(r["状态"])
                    if "🔴" in s:
                        return ["background-color: #FADBD8; color: #78281F; font-weight: bold"] * len(r)
                    elif "🟡" in s:
                        return ["background-color: #FCF3CF; color: #7D6608; font-weight: bold"] * len(r)
                    return ["background-color: #E8F8F5; color: #0E6251"] + [""] * (len(r) - 1)

                mobile_live_cols = ["状态", "位次", "成员名称", "出刀", "得星"]
                st.dataframe(
                    show_live[mobile_live_cols].style.apply(style_live, axis=1),
                    use_container_width=True,
                    height=460,
                    hide_index=True,
                )

                zero_df = live_df[live_df["剩余"] == atk_limit]
                one_df = live_df[(live_df["剩余"] > 0) & (live_df["剩余"] < atk_limit)]
                if state == "inWar" and (not zero_df.empty or not one_df.empty):
                    st.markdown("**📢 一键复制实时催刀通知**")
                    txt_lines = [
                        f"【{ACTIVE_NAME} 部落战催刀】剩余 {remain_str}",
                        f"比分：{clan_info.get('stars', 0)}★ vs {opp_info.get('stars', 0)}★",
                        "",
                    ]
                    if not zero_df.empty:
                        txt_lines.append("🔴 一刀未出：")
                        txt_lines.append("、".join(f"{r['位次']}{r['成员名称']}" for _, r in zero_df.iterrows()))
                        txt_lines.append("")
                    if not one_df.empty:
                        txt_lines.append("🟡 还剩 1 刀：")
                        txt_lines.append("、".join(f"{r['位次']}{r['成员名称']}" for _, r in one_df.iterrows()))
                    st.code("\n".join(txt_lines), language="text")
        except Exception as e:
            st.error(f"获取实时部落战失败：{e}")

with tab_history:
    if not os.path.exists(WAR_HISTORY_FILE):
        st.info("💡 `war_history.csv` 尚未生成，请先去 GitHub 仓库的 **Actions** 页面点击 **Run workflow** 触发首次抓拍。")
    else:
        raw_hist = pd.read_csv(WAR_HISTORY_FILE)
        if "clan_tag" not in raw_hist.columns:
            raw_hist["clan_tag"] = "#2YR9JVCG8"

        hist_df = raw_hist[raw_hist["clan_tag"].astype(str).str.upper() == ACTIVE_TAG].copy()

        if hist_df.empty:
            st.info(f"**{ACTIVE_NAME} ({ACTIVE_TAG})** 暂无常规战自动归档记录，开战后每30分钟会自动抓拍入库。")
        else:
            unique_wars = sorted(hist_df["war_id"].astype(str).unique().tolist())
            total_recorded = len(unique_wars)
            default_n = min(15, total_recorded)

            if total_recorded <= 1:
                last_n = 1
                st.caption(f"📌 当前 {ACTIVE_NAME} 已归档 1 场常规战（积累 2 场及以上后可滑动选择场次范围）")
            else:
                last_n = st.slider(
                    f"统计最近几场（{ACTIVE_NAME} 已归档 {total_recorded} 场）",
                    min_value=1,
                    max_value=total_recorded,
                    value=default_n,
                )

            col_f1, col_f2 = st.columns(2)
            with col_f1:
                only_miss_hist = st.checkbox("仅看漏打成员", value=False, key="hist_only_miss")
            with col_f2:
                show_full_cols = st.checkbox("展开详细星数列", value=False, key="hist_full_cols")

            target_war_ids = set(unique_wars[-last_n:])
            sub = hist_df[hist_df["war_id"].astype(str).isin(target_war_ids)].copy()

            grouped = (
                sub.groupby(["player_tag", "player_name"], as_index=False)
                .agg(
                    大本营=("town_hall", "max"),
                    参战场次=("war_id", "nunique"),
                    应出刀数=("attacks_per_member", "sum"),
                    实际出刀=("attacks_used", "sum"),
                    漏打刀数=("attacks_missed", "sum"),
                    总得星=("total_stars", "sum"),
                    三星数=("three_stars", "sum"),
                )
            )
            grouped["漏刀率(%)"] = (grouped["漏打刀数"] / grouped["应出刀数"] * 100).round(1)
            grouped["刀均得星"] = grouped.apply(
                lambda r: round(r["总得星"] / r["实际出刀"], 2) if r["实际出刀"] > 0 else 0.0, axis=1
            )
            grouped["三星率(%)"] = grouped.apply(
                lambda r: round(r["三星数"] / r["实际出刀"] * 100, 1) if r["实际出刀"] > 0 else 0.0, axis=1
            )
            grouped["出勤"] = grouped.apply(lambda r: f"{r['实际出刀']}/{r['应出刀数']}", axis=1)

            def tag_hist_status(r):
                if r["漏打刀数"] >= 6 or (r["漏打刀数"] > 0 and r["实际出刀"] == 0):
                    return "🔴 严重"
                elif r["漏打刀数"] > 0:
                    return "🟡 漏打"
                return "🟢 全勤"

            grouped["状态"] = grouped.apply(tag_hist_status, axis=1)
            grouped = grouped.sort_values(
                by=["漏打刀数", "漏刀率(%)", "参战场次", "总得星"],
                ascending=[False, False, False, False],
            ).reset_index(drop=True)
            grouped = grouped.rename(columns={"player_name": "成员名称", "player_tag": "玩家标签"})

            render_kpi_grid([
                ("统计场次", f"近 {len(target_war_ids)} 场", ""),
                ("全勤人数", f"{int((grouped['漏打刀数'] == 0).sum())} 人", "ok"),
                ("漏打人数", f"{int((grouped['漏打刀数'] > 0).sum())} 人", "alert"),
                ("累计漏刀", f"{int(grouped['漏打刀数'].sum())} 刀", "alert"),
            ])

            view_hist = grouped[grouped["漏打刀数"] > 0] if only_miss_hist else grouped

            compact_cols = ["状态", "成员名称", "出勤", "漏打刀数", "漏刀率(%)"]
            detail_cols = [
                "状态", "成员名称", "大本营", "参战场次", "出勤",
                "漏打刀数", "漏刀率(%)", "总得星", "刀均得星", "三星率(%)"
            ]
            use_cols = detail_cols if show_full_cols else compact_cols

            def style_hist(r):
                s = str(r["状态"])
                if "严重" in s:
                    return ["background-color: #FADBD8; color: #78281F; font-weight: bold"] * len(r)
                elif "漏打" in s:
                    return ["background-color: #FCF3CF; color: #7D6608; font-weight: bold"] * len(r)
                return ["background-color: #E8F8F5; color: #0E6251"] + [""] * (len(r) - 1)

            fmt_dict = {"漏刀率(%)": "{:.1f}%"}
            if show_full_cols:
                fmt_dict.update({"三星率(%)": "{:.1f}%", "刀均得星": "{:.2f}"})

            st.dataframe(
                view_hist[use_cols].style.apply(style_hist, axis=1).format(fmt_dict),
                use_container_width=True,
                height=460,
                hide_index=True,
            )

            st.download_button(
                label=f"⬇️ 下载 {ACTIVE_NAME} 常规战出勤表 (.xlsx)",
                data=build_excel_bytes(view_hist[detail_cols], f"{ACTIVE_NAME}常规战"),
                file_name=f"{ACTIVE_NAME}_最近{len(target_war_ids)}场出勤统计.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

            sev = grouped[grouped["状态"].str.contains("严重")]
            min_l = grouped[grouped["状态"].str.contains("漏打")]
            msg = [
                f"【{ACTIVE_NAME} 近{len(target_war_ids)}场部落战通报】",
                f"全勤 {int((grouped['漏打刀数'] == 0).sum())} 人 | 漏打 {int((grouped['漏打刀数'] > 0).sum())} 人（共漏 {int(grouped['漏打刀数'].sum())} 刀）",
                "",
                "🔴 严重漏打 / 全鸽名单：",
            ]
            for _, r in sev.iterrows():
                msg.append(f"- {r['成员名称']}：漏 {r['漏打刀数']} 刀（出勤 {r['出勤']}，漏刀率 {r['漏刀率(%)']}%）")
            msg.append("")
            msg.append("🟡 一般漏打提醒：")
            for _, r in min_l.iterrows():
                msg.append(f"- {r['成员名称']}：漏 {r['漏打刀数']} 刀（出勤 {r['出勤']}）")
            st.markdown("**📢 一键复制群通知**")
            st.code("\n".join(msg), language="text")

with tab_cwl:
    token = get_secret_val("COC_API_TOKEN")
    cwl_frames = []

    if os.path.exists(CWL_HISTORY_FILE):
        saved_cwl = pd.read_csv(CWL_HISTORY_FILE)
        if not saved_cwl.empty:
            cwl_frames.append(saved_cwl[saved_cwl["clan_tag"].astype(str).str.upper() == ACTIVE_TAG])

    if token:
        try:
            live_cwl = fetch_live_cwl_rows(ACTIVE_TAG, ACTIVE_NAME, token)
            if not live_cwl.empty:
                cwl_frames.append(live_cwl)
        except Exception:
            pass

    if not cwl_frames or all(df.empty for df in cwl_frames):
        st.info(
            f"📅 **{ACTIVE_NAME} ({ACTIVE_TAG})** 暂无七天联赛记录。\n\n"
            "每月月初开启部落对战联赛（CWL）后，后台每 30 分钟会自动抓拍 **DAY 1 至 DAY 7** 每一天的上场名单、出刀与得星，"
            "并自动同步备份到你的 Google Sheet 中。"
        )
    else:
        all_cwl = pd.concat([df for df in cwl_frames if not df.empty], ignore_index=True)
        all_cwl["round_num"] = all_cwl["round_num"].astype(int)
        all_cwl = all_cwl.drop_duplicates(subset=["season", "round_num", "player_tag"], keep="last")

        seasons = sorted(all_cwl["season"].astype(str).unique().tolist(), reverse=True)
        selected_season = st.selectbox("📆 选择联赛赛季", options=seasons, index=0)
        s_df = all_cwl[all_cwl["season"].astype(str) == selected_season].copy()

        col_c1, col_c2 = st.columns(2)
        with col_c1:
            cwl_only_miss = st.checkbox("仅看有漏刀成员", value=False, key="cwl_only_miss")
        with col_c2:
            cwl_under_8 = st.checkbox("筛选未满 8 星成员", value=False, key="cwl_under_8")

        day_lookup = {}
        for _, r in s_df.iterrows():
            key = (r["player_tag"], int(r["round_num"]))
            if int(r["attacks_used"]) > 0:
                day_lookup[key] = f"{int(r['stars'])}★"
            elif str(r["war_state"]) == "warEnded":
                day_lookup[key] = "❌漏"
            else:
                day_lookup[key] = "⏳待"

        cwl_grouped = (
            s_df.groupby(["player_tag", "player_name"], as_index=False)
            .agg(
                大本营=("town_hall", "max"),
                上场天数=("round_num", "nunique"),
                已出刀=("attacks_used", "sum"),
                漏打刀数=("attacks_missed", "sum"),
                总得星=("stars", "sum"),
            )
        )

        ended_missed_map = (
            s_df[s_df["war_state"] == "warEnded"]
            .groupby("player_tag")["attacks_missed"]
            .sum()
            .to_dict()
        )
        cwl_grouped["确认漏刀"] = cwl_grouped["player_tag"].map(lambda t: int(ended_missed_map.get(t, 0)))

        for d in range(1, 8):
            cwl_grouped[f"D{d}"] = cwl_grouped["player_tag"].map(lambda t: day_lookup.get((t, d), "—"))

        def tag_cwl_status(r):
            if r["确认漏刀"] > 0:
                return f"🔴 漏{r['确认漏刀']}刀"
            elif r["总得星"] >= 8:
                return "⭐ 满8星"
            return "🟢 未满8星"

        cwl_grouped["状态"] = cwl_grouped.apply(tag_cwl_status, axis=1)
        cwl_grouped["出勤"] = cwl_grouped.apply(lambda r: f"{r['已出刀']}/{r['上场天数']}", axis=1)
        cwl_grouped = cwl_grouped.sort_values(
            by=["确认漏刀", "总得星", "上场天数"],
            ascending=[False, False, False],
        ).reset_index(drop=True)
        cwl_grouped = cwl_grouped.rename(columns={"player_name": "成员名称", "player_tag": "玩家标签"})

        recorded_days = int(s_df["round_num"].max())
        render_kpi_grid([
            ("联赛进度", f"已录 {recorded_days}/7 天", ""),
            ("参战人数", f"{len(cwl_grouped)} 人", ""),
            ("已满 8 星", f"{int((cwl_grouped['总得星'] >= 8).sum())} 人", "ok"),
            ("确认漏刀", f"{int(cwl_grouped['确认漏刀'].sum())} 刀", "alert"),
        ])

        cwl_view = cwl_grouped.copy()
        if cwl_only_miss:
            cwl_view = cwl_view[cwl_view["确认漏刀"] > 0]
        if cwl_under_8:
            cwl_view = cwl_view[cwl_view["总得星"] < 8]

        cwl_cols = ["状态", "成员名称", "出勤", "总得星", "D1", "D2", "D3", "D4", "D5", "D6", "D7"]

        def style_cwl(r):
            s = str(r["状态"])
            if "🔴" in s:
                return ["background-color: #FADBD8; color: #78281F; font-weight: bold"] * len(r)
            elif "⭐" in s:
                return ["background-color: #E8F8F5; color: #0E6251; font-weight: bold"] + [""] * (len(r) - 1)
            return ["background-color: #FCF3CF; color: #7D6608"] + [""] * (len(r) - 1)

        st.dataframe(
            cwl_view[cwl_cols].style.apply(style_cwl, axis=1),
            use_container_width=True,
            height=480,
            hide_index=True,
        )
        st.caption("图例：`3★` 得星数 ｜ `❌漏` 已结束未出刀 ｜ `⏳待` 当天战斗日进行中 ｜ `—` 当天未上场轮休")

        st.download_button(
            label=f"⬇️ 下载 {ACTIVE_NAME} ({selected_season}) 七天联赛表 (.xlsx)",
            data=build_excel_bytes(cwl_view[cwl_cols], f"{ACTIVE_NAME}联赛_{selected_season}"),
            file_name=f"{ACTIVE_NAME}_{selected_season}_七天联赛统计.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

        miss_cwl = cwl_grouped[cwl_grouped["确认漏刀"] > 0]
        eight_cwl = cwl_grouped[cwl_grouped["总得星"] >= 8]
        under8_cwl = cwl_grouped[(cwl_grouped["总得星"] < 8) & (cwl_grouped["确认漏刀"] == 0)]

        cwl_msg = [
            f"【{ACTIVE_NAME} {selected_season} 联赛战况通报（第 {recorded_days}/7 天）】",
            "",
            "🔴 联赛漏刀名单（按规撤下）：",
        ]
        if miss_cwl.empty:
            cwl_msg.append("- 暂无漏刀，全员出勤！")
        else:
            for _, r in miss_cwl.iterrows():
                cwl_msg.append(f"- {r['成员名称']}：漏 {r['确认漏刀']} 刀（当前 {r['总得星']}★，出勤 {r['出勤']}）")

        cwl_msg.append("")
        cwl_msg.append(f"⭐ 已满 8 星成员（共 {len(eight_cwl)} 人，可安排轮换）：")
        if eight_cwl.empty:
            cwl_msg.append("- 暂无")
        else:
            cwl_msg.append("、".join(f"{r['成员名称']}({r['总得星']}★)" for _, r in eight_cwl.iterrows()))

        cwl_msg.append("")
        cwl_msg.append(f"🟡 尚差星数满 8 星（共 {len(under8_cwl)} 人，优先安排上场）：")
        if under8_cwl.empty:
            cwl_msg.append("- 暂无")
        else:
            cwl_msg.append("、".join(f"{r['成员名称']}({r['总得星']}★)" for _, r in under8_cwl.iterrows()))

        st.markdown("**📢 一键复制联赛轮换与漏刀通报**")
        st.code("\n".join(cwl_msg), language="text")
