import streamlit as st
import subprocess
import json
import re
from datetime import date
import pandas as pd
from google import genai
from pydantic import BaseModel
from streamlit_gsheets import GSheetsConnection

st.set_page_config(page_title="InstaRecipe", page_icon="🍳", layout="centered")

# Data Models
class Ingredient(BaseModel):
    item: str
    quantity: str
    aisle: str

class Recipe(BaseModel):
    title: str
    shopping_list: list[Ingredient]
    instructions: list[str]

# Extraction Helpers
def get_instagram_caption(url: str) -> str:
    cmd = ["yt-dlp", "--dump-json", "--skip-download", url]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return ""
    try:
        data = json.loads(result.stdout)
        return data.get("description", "")
    except Exception:
        return ""

def parse_with_gemini(text: str, api_key: str) -> Recipe:
    client = genai.Client(api_key=api_key.strip())
    prompt = f"""
    Extract the shopping list and cooking instructions from this text.
    Return strictly a valid JSON object matching this exact format:
    {{
      "title": "Recipe Title",
      "shopping_list": [
        {{"item": "Garlic", "quantity": "3 cloves", "aisle": "Produce"}}
      ],
      "instructions": [
        "Step 1 text",
        "Step 2 text"
      ]
    }}

    Categorize aisle into one of: Produce, Meat/Seafood, Dairy, Pantry, Bakery, or Other.
    Do not wrap with markdown fences or extra explanations.

    Text:
    ---
    {text}
    ---
    """
    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt,
        config={"response_mime_type": "application/json"}
    )
    raw_text = response.text.strip()
    if raw_text.startswith("```"):
        raw_text = re.sub(r"^```[a-zA-Z]*\n", "", raw_text)
        raw_text = re.sub(r"\n```$", "", raw_text)
    return Recipe.model_validate(json.loads(raw_text))

# Database Helpers
def get_db():
    return st.connection("gsheets", type=GSheetsConnection)

def load_recipes(conn):
    try:
        df = conn.read(ttl=0)
        if df is None or df.empty or "title" not in df.columns:
            return pd.DataFrame(columns=["title", "date_added", "recipe_json"])
        return df.dropna(subset=["title"])
    except Exception as e:
        return pd.DataFrame(columns=["title", "date_added", "recipe_json"])

def save_recipe(conn, recipe: Recipe):
    df = load_recipes(conn)
    new_row = pd.DataFrame([{
        "title": recipe.title,
        "date_added": str(date.today()),
        "recipe_json": recipe.model_dump_json()
    }])
    updated = pd.concat([df, new_row], ignore_index=True)
    conn.update(data=updated)

def delete_recipe(conn, title_to_remove: str):
    df = load_recipes(conn)
    updated = df[df["title"] != title_to_remove]
    conn.update(data=updated)

# Initialize Storage & Sidebar
try:
    conn = get_db()
    saved_df = load_recipes(conn)
except Exception as e:
    conn = None
    saved_df = pd.DataFrame()

with st.sidebar:
    st.header("📚 Saved Recipes")
    if not saved_df.empty:
        recipe_titles = saved_df["title"].tolist()
        choice = st.selectbox("Your Library:", ["-- Create / Paste New --"] + recipe_titles)
        
        if choice != "-- Create / Paste New --":
            selected_row = saved_df[saved_df["title"] == choice].iloc[-1]
            st.session_state["recipe"] = Recipe.model_validate_json(selected_row["recipe_json"])
            
            if st.button("🗑️ Delete Recipe", use_container_width=True):
                delete_recipe(conn, choice)
                st.success("Deleted!")
                st.rerun()
    else:
        st.info("No saved recipes yet.")

# Main Application Body
st.title("🍳 Recipe Extractor")
saved_key = st.secrets.get("GEMINI_API_KEY", "")
api_key = saved_key if saved_key else st.text_input("Gemini API Key", type="password")

post_url = st.text_input("Instagram URL", placeholder="[https://www.instagram.com/reel/](https://www.instagram.com/reel/)...")

if st.button("Extract Recipe", type="primary", use_container_width=True):
    if not post_url:
        st.warning("Please enter an Instagram link first.")
    elif not api_key:
        st.error("Missing Gemini API Key.")
    else:
        with st.spinner("Extracting content and parsing recipe..."):
            caption = get_instagram_caption(post_url)
            if not caption:
                st.error("Could not fetch caption. Ensure the link is public.")
            else:
                try:
                    recipe = parse_with_gemini(caption, api_key)
                    st.session_state["recipe"] = recipe
                except Exception as e:
                    st.error(f"Error communicating with Gemini: {str(e)}")

# Display Selected / Extracted Recipe
if "recipe" in st.session_state:
    rec = st.session_state["recipe"]
    st.divider()
    st.header(rec.title)

    # Save Button (Always Visible)
    if st.button("💾 Save to Library", use_container_width=True):
        if not conn:
            st.error("Google Sheets connection not initialized. Please verify [connections.gsheets] in Streamlit Secrets.")
        else:
            try:
                save_recipe(conn, rec)
                st.success(f"Saved '{rec.title}' to your Google Sheet!")
                st.rerun()
            except Exception as e:
                st.error(f"Save failed: {e}")

    tab1, tab2 = st.tabs(["🛒 Shopping List", "👨‍🍳 Instructions"])

    with tab1:
        by_aisle = {}
        for ing in rec.shopping_list:
            by_aisle.setdefault(ing.aisle, []).append(ing)

        for aisle, items in by_aisle.items():
            st.subheader(aisle)
            for item in items:
                st.checkbox(f"{item.quantity} — {item.item}", key=f"{aisle}_{item.item}_{rec.title}")

    with tab2:
        for idx, step in enumerate(rec.instructions, 1):
            st.markdown(f"**Step {idx}**")
            st.write(step)
