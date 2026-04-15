import streamlit as st
import requests
import ast
import json
import pandas as pd

API_URL = "https://blueverse-foundry.ltimindtree.com/chatservice/chat"
SPACE_NAME = "SmartTicketOpsAgent_f8c1eb34"
FLOW_ID = "69c22612db07d4f23c573344"

DEFAULT_TOKEN = "dbfdbfb"

result = {}

ENABLE_EXTERNAL_FALLBACK = False  


def call_claude_fallback(user_text):
    raise NotImplementedError("Claude fallback not configured")

def call_openai_fallback(user_text):
    raise NotImplementedError("OpenAI/Gemini fallback not configured")

def risk_color(value):
    return {
        "Low": "#2ecc71",
        "Medium": "#f1c40f",
        "High": "#e74c3c",
        "Critical": "#c0392b"
    }.get(value, "#95a5a6")

def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def call_agent(token, user_text):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }

    payload = {
        "query": user_text,
        "userRequest": user_text,
        "space_name": SPACE_NAME,
        "flowId": FLOW_ID
    }

    r = requests.post(API_URL, headers=headers, json=payload, timeout=(10, 120))
    r.raise_for_status()
    return r.json()


def call_agent_with_fallback(token, user_text):
    try:
        return call_agent(token, user_text)  
    except Exception as e:
        if not ENABLE_EXTERNAL_FALLBACK:
            raise RuntimeError(f"BlueVerse failed and fallback disabled: {str(e)}")

        try:
            return call_claude_fallback(user_text)
        except Exception:
            try:
                return call_openai_fallback(user_text)
            except Exception:
                raise RuntimeError("All LLM providers failed")



def parse_agent_response(api_response):
    raw = api_response.get("response", "")
    if not raw:
        return {}
    try:
        return json.loads(raw) 
    except Exception:
        try:
            return ast.literal_eval(raw) 
        except Exception:
            return {}


def post_process_agent_output(result: dict) -> dict:
    RESOLVER_MAP = {
        "Oracle Fusion Payroll Team": "Payroll Support Team",
        "Payroll Support": "Payroll Support Team",
        "Finance Applications Team": "Finance Applications Team",
        "Financial Applications Team": "Finance Applications Team",
        "Finance Technical Team": "Finance Applications Team",
        "Oracle Fusion Technical Team": "Finance Applications Team",
        "BI Analytics Team": "BI/Analytics Team",
        "Infrastructure Team": "System Performance Team",
    }

    resolver = result.get("resolver_group")
    if resolver in RESOLVER_MAP:
        result["resolver_group"] = RESOLVER_MAP[resolver]

    if not result.get("is_recurring_issue", False):
        if result.get("severity") in ["Critical", "High"]:
            result["similar_ticket_count"] = max(
                result.get("similar_ticket_count", 0), 3
            )

    pim = result.get("patch_impacted_modules")
    if isinstance(pim, dict):
        result["patch_impacted_modules"] = {
            str(k): str(v) for k, v in pim.items()
        }
    else:
        result["patch_impacted_modules"] = {}

    return result




st.set_page_config(page_title="AI‑Driven Ticket Operations", layout="wide")

st.title("AI‑Driven Ticket Operations")
st.caption("Auto‑Ticket Classification, Routing & SLA Prediction")

st.sidebar.header("Configuration")
token = st.sidebar.text_input("BlueVerse API Token", value=DEFAULT_TOKEN, type="password")


st.subheader("Input Mode")

input_mode = st.radio(
    "Choose how you want to analyze tickets",
    ["Single Ticket Text", "Upload Excel File"],
    horizontal=True
)


with st.expander("Excel Upload Format (Important)"):
    st.markdown("""
    ### Expected Excel Format

    Your Excel file should contain **one ticket per row** with the following columns:

    **Required columns**
    - `short_description`
    - `description`

    **Optional columns (recommended)**
    - `ticket_id`
    - `priority`
    - `assignment_group`
    - `application`
    - `ticket_type` (Incident / Change / Request)

    The AI agent will combine **short_description + description** to analyze each ticket.
    """

    )


user_input = ""
uploaded_file = None

if input_mode == "Single Ticket Text":
    st.subheader("Ticket Description")
    user_input = st.text_area(
        "Enter ticket details",
        height=150,
        placeholder="Example: Fusion quarterly patch applied last night. Users reporting issues in Payroll and HCM modules."
    )

elif input_mode == "Upload Excel File":
    st.subheader("Upload Ticket Excel File")
    uploaded_file = st.file_uploader(
        "Upload Excel (.xlsx) file",
        type=["xlsx"]
    )



run_btn = st.button("Analyze")

if run_btn and input_mode == "Single Ticket Text":
    if not token or not user_input.strip():
        st.error("Please provide API token and ticket text.")
    else:
        with st.spinner("Calling AI agent..."):
            try:
                api_resp = call_agent_with_fallback(token, user_input)                
                result = post_process_agent_output(
                    parse_agent_response(api_resp)
                )
                if not result:
                    st.error("Could not parse agent response.")
                else:
                    st.spinner("Loading")

            except Exception as e:
                st.error(f"Error calling agent: {e}")



if run_btn and input_mode == "Upload Excel File":
    if not token or uploaded_file is None:
        st.error("Please provide API token and upload an Excel file.")
    else:
        df = pd.read_excel(uploaded_file)

        required_cols = {"short_description", "description"}
        if not required_cols.issubset(df.columns):
            st.error(
                f"Excel file must contain columns: {required_cols}"
            )
        else:
            results = []

            batch_input_tokens = 0
            batch_output_tokens = 0
            batch_success = 0
            batch_failed = 0
            ESTIMATED_COST_PER_INTERACTION = 0.003

            progress = st.progress(0)
            total_rows = len(df)

            for idx, row in df.iterrows():
                combined_text = f"{row['short_description']} {row['description']}"

                combined_text = f"{row['short_description']} {row['description']}"
                batch_input_tokens += estimate_tokens(combined_text)

                try:
                    api_resp = call_agent_with_fallback(token, combined_text)                    
                    parsed = post_process_agent_output(
                        parse_agent_response(api_resp)
                    )
                    batch_output_tokens += estimate_tokens(json.dumps(parsed))
                    batch_success += 1

                except Exception as e:
                    parsed = {"error": str(e)}
                    batch_failed += 1
                    err = str(e)
                    parsed = {"error": err}
                    if "401" in err or "403" in err:
                        st.error("Token expired during batch run. Please refresh token and rerun.")
                        break

                parsed["source_row"] = idx + 1
                results.append(parsed)

                progress.progress((idx + 1) / total_rows)

            results_df = pd.DataFrame(results)


            if "patch_impacted_modules" in results_df.columns:
                results_df["patch_impacted_modules"] = results_df["patch_impacted_modules"].apply(
                    lambda x: json.dumps(x, indent=2) if isinstance(x, dict) else x
                )

            st.success("Batch analysis completed")

            st.subheader("Batch Analysis Results")
            st.dataframe(results_df)

            total_tokens = batch_input_tokens + batch_output_tokens
            batch_cost = (batch_success + batch_failed) * ESTIMATED_COST_PER_INTERACTION

            st.sidebar.markdown(f"""
            ### Batch Token Usage (Estimated)
            - Rows processed: {batch_success + batch_failed}
            - Success: {batch_success}
            - Failed: {batch_failed}
            - Input tokens: {batch_input_tokens}
            - Output tokens: {batch_output_tokens}
            - Total tokens: {total_tokens}

            ### Batch Cost (Estimated)
            - Cost / row: ${ESTIMATED_COST_PER_INTERACTION}
            - Total cost: ${batch_cost:.3f}
            """)

            st.download_button(
                "Download Results as CSV",
                data=results_df.to_csv(index=False),
                file_name="ticket_analysis_results.csv",
                mime="text/csv"
            )


input_tokens = estimate_tokens(user_input)
output_tokens = estimate_tokens(json.dumps(result))
total_tokens = input_tokens + output_tokens

st.sidebar.markdown(f"""
### Token Usage (Estimated)
- Input tokens: {input_tokens}
- Output tokens: {output_tokens}
- Total tokens: {total_tokens}
""")



ESTIMATED_COST_PER_INTERACTION = 0.003

st.sidebar.markdown(f"""
### Cost Tracking
Estimated cost per interaction: **${ESTIMATED_COST_PER_INTERACTION}**
""")



st.markdown("## Ticket Analysis Summary")

c1, c2, c3, c4 = st.columns(4)

with c1:
    st.markdown(
        f"""
        <div style="padding:15px;border-radius:10px;background:#f8f9fa">
        <b>Module</b><br>
        <span style="font-size:22px">{result.get("module","—")}</span>
        </div>
        """,
        unsafe_allow_html=True
    )

with c2:
    sev = result.get("severity", "—")
    st.markdown(
        f"""
        <div style="padding:15px;border-radius:10px;background:{risk_color(sev)};color:white">
        <b>Severity</b><br>
        <span style="font-size:22px">{sev}</span>
        </div>
        """,
        unsafe_allow_html=True
    )

with c3:
    st.markdown(
        f"""
        <div style="padding:15px;border-radius:10px;background:#f8f9fa">
        <b>Ticket Type</b><br>
        <span style="font-size:22px">{result.get("ticket_type","—")}</span>
        </div>
        """,
        unsafe_allow_html=True
    )

with c4:
    st.markdown(
        f"""
        <div style="padding:15px;border-radius:10px;background:#f8f9fa">
        <b>Resolver Group</b><br>
        <span style="font-size:18px">{result.get("resolver_group","—")}</span>
        </div>
        """,
        unsafe_allow_html=True
    )

st.markdown("---")

c5, c6 = st.columns(2)

with c5:
    st.markdown(
        f"""
        <div style="padding:20px;border-radius:12px;background:#eef2f7">
        <b>Priority</b><br>
        <span style="font-size:26px">{result.get("priority","—")}</span>
        </div>
        """,
        unsafe_allow_html=True
    )

with c6:
    risk = result.get("sla_breach_risk", "—")
    st.markdown(
        f"""
        <div style="padding:20px;border-radius:12px;background:{risk_color(risk)};color:white">
        <b>SLA Breach Risk</b><br>
        <span style="font-size:26px">{risk}</span>
        </div>
        """,
        unsafe_allow_html=True
    )

st.markdown("---")

st.markdown("## SLA Risk Analysis")

sla_conf = float(result.get("sla_confidence", 0))
sla_pct = int(sla_conf * 100)

st.markdown(
    f"""
    <b>Risk Confidence:</b> {sla_pct}%<br>
    <span style="color:#555">{result.get("sla_breach_reason","—")}</span>
    """,
    unsafe_allow_html=True
)

st.progress(sla_conf)

st.markdown("---")

st.markdown("## Patch Impacted Modules")

patches = result.get("patch_impacted_modules", {})
if patches:
    for mod, impact in patches.items():
        st.markdown(
            f"""
            <div style="padding:12px;margin-bottom:8px;border-left:6px solid #3498db;background:#f8f9fa">
            <b>{mod}</b><br>
            <span style="color:#555">{impact}</span>
            </div>
            """,
            unsafe_allow_html=True
        )
else:
    st.info("No patch impact detected.")

with st.expander("View Raw Agent Output"):
    st.json(result)
