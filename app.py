import streamlit as st
import subprocess
import json
import re
from google import genai
from pydantic import BaseModel

st.set_page_config(page_title="InstaRecipe", page_icon="🍳", layout="centered")

st.title("🍳 Recipe Extractor")
st.caption("Paste an Instagram link to extract ingredients and instructions.")

# Data Models
class Ingredient(BaseModel):
    item: str
    quantity: str
    aisle: str

class Recipe(BaseModel):
    title: str
    shopping_list: list[Ingredient]
    instructions: list[str]

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
    # Clean whitespace from the key
    clean_key = api_key.strip()
    client = genai.Client(api_key=clean_key)
    
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
    
    # Request JSON response format
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config={"response_mime_type": "application/json"}
    )
    
    raw_text = response.text.strip()
    # Strip markdown if present
    if raw_text.startswith("```"):
        raw_text = re.sub(r"^```[a-zA-Z]*\n", "", raw_text)
        raw_text = re.sub(r"\n```$", "", raw_text)
    
    parsed_json = json.loads(raw_text)
    return Recipe.model_validate(parsed_json)

# Check secrets or allow manual input
saved_key = st.secrets.get("GEMINI_API_KEY", "")
api_key = saved_key if saved_key else st.text_input("Gemini API Key", type="password")

post_url = st.text_input("Instagram URL", placeholder="[https://www.instagram.com/reel/](https://www.instagram.com/reel/)...")

if st.button("Extract Recipe", type="primary", use_container_width=True):
    if not post_url:
        st.warning("Please enter an Instagram link first.")
    elif not api_key:
        st.error("Missing Gemini API Key. Add it to Streamlit Secrets or enter it above.")
    else:
        with st.spinner("Extracting content and parsing recipe..."):
            caption = get_instagram_caption(post_url)
            if not caption:
                st.error("Could not fetch caption. Ensure the link is public and yt-dlp can reach it.")
            else:
                try:
                    recipe = parse_with_gemini(caption, api_key)
                    st.session_state["recipe"] = recipe
                except Exception as e:
                    # Displays the real unredacted Google error message
                    st.error(f"Error communicating with Gemini: {str(e)}")

# Display Recipe
if "recipe" in st.session_state:
    rec = st.session_state["recipe"]
    st.header(rec.title)
    
    tab1, tab2 = st.tabs(["🛒 Shopping List", "👨‍🍳 Instructions"])
    
    with tab1:
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
