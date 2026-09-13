import streamlit as st
import subprocess
import json
from google import genai
from google.genai import types
from pydantic import BaseModel

# 1. Configure the Mobile View
st.set_page_config(page_title="InstaRecipe", page_icon="🍳", layout="centered")

st.title("🍳 Recipe Extractor")
st.caption("Paste an Instagram link to generate an ingredient list and cooking instructions.")

# 2. Define Data Structures
class Ingredient(BaseModel):
    item: str
    quantity: str
    aisle: str

class Recipe(BaseModel):
    title: str
    shopping_list: list[Ingredient]
    instructions: list[str]

# 3. Helper to Extract Content from Instagram
def get_instagram_caption(url: str) -> str:
    cmd = ["yt-dlp", "--dump-json", "--skip-download", url]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return ""
    data = json.loads(result.stdout)
    return data.get("description", "")

# 4. Helper to Parse with Gemini
def parse_with_gemini(text: str, api_key: str) -> Recipe:
    client = genai.Client(api_key=api_key)
    prompt = f"""
    Extract the shopping list and cooking instructions from this Instagram post:
    ---
    {text}
    ---
    Classify aisle names into: Produce, Meat/Seafood, Dairy, Pantry, or Bakery.
    """
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=Recipe,
        ),
    )
    return Recipe.model_validate_json(response.text)

# 5. UI Elements
api_key = st.secrets.get("GEMINI_API_KEY") if "GEMINI_API_KEY" in st.secrets else st.text_input("Gemini API Key", type="password")
post_url = st.text_input("Instagram URL", placeholder="https://www.instagram.com/reel/...")

if st.button("Extract Recipe", type="primary", use_container_width=True):
    if not post_url:
        st.warning("Please enter an Instagram link first.")
    elif not api_key:
        st.error("Please provide a Gemini API key.")
    else:
        with st.spinner("Extracting post and formatting recipe..."):
            caption = get_instagram_caption(post_url)
            if not caption:
                st.error("Could not fetch caption. Ensure the link is public.")
            else:
                recipe = parse_with_gemini(caption, api_key)
                st.session_state["recipe"] = recipe

# 6. Display Output
if "recipe" in st.session_state:
    rec = st.session_state["recipe"]
    st.header(rec.title)
    
    tab1, tab2 = st.tabs(["🛒 Shopping List", "👨‍🍳 Instructions"])
    
    with tab1:
        # Group ingredients by aisle
        by_aisle = {}
        for ing in rec.shopping_list:
            by_aisle.setdefault(ing.aisle, []).append(ing)
            
        for aisle, items in by_aisle.items():
            st.subheader(aisle)
            for item in items:
                st.checkbox(f"{item.quantity} — {item.item}", key=f"{aisle}_{item.item}")

    with tab2:
        for idx, step in enumerate(rec.instructions, 1):
            st.markdown(f"**Step {idx}**")
            st.write(step)
