import os
from urllib.parse import urlparse

os.environ.setdefault("USER_AGENT", "Mozilla/5.0 (compatible; WebpageQABot/1.0)")

import streamlit as st
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain.prompts import ChatPromptTemplate
from langchain_community.document_loaders import WebBaseLoader
from langchain_openai import ChatOpenAI


st.set_page_config(
    page_title="Webpage Q&A",
    page_icon="🌐",
    layout="wide",
)

st.markdown(
    """
    <style>
    .stApp {
        background:
            radial-gradient(ellipse at 12% 0%, rgba(43, 105, 190, .18), transparent 38%),
            #0b1020;
        color: #edf3ff;
    }
    .block-container {
        max-width: 1050px;
        padding-top: 3rem;
        padding-bottom: 4rem;
    }
    .hero-kicker {
        color: #8dbbff;
        font-size: .8rem;
        font-weight: 700;
        letter-spacing: .16em;
        text-transform: uppercase;
    }
    .hero-title {
        color: #f4f7ff;
        font-size: clamp(2.5rem, 6vw, 4.4rem);
        font-weight: 750;
        letter-spacing: -.055em;
        line-height: 1.05;
        margin: .5rem 0;
    }
    .hero-copy {
        color: #aab7d0;
        font-size: 1.08rem;
        max-width: 650px;
        margin-bottom: 2rem;
    }
    div[data-testid="stForm"] {
        background: rgba(21, 29, 50, .82);
        border: 1px solid rgba(148, 175, 220, .18);
        border-radius: 18px;
        padding: 1.4rem 1.5rem;
    }
    div.stButton > button[kind="primary"] {
        background: linear-gradient(100deg, #3478f6, #6958e8);
        border: 0;
        border-radius: 10px;
        font-weight: 650;
        min-height: 2.8rem;
    }
    div[data-testid="stAlert"] {
        border-radius: 12px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown('<div class="hero-kicker">Read less. Understand more.</div>', unsafe_allow_html=True)
st.markdown('<h1 class="hero-title">Ask any webpage.</h1>', unsafe_allow_html=True)
st.markdown(
    '<p class="hero-copy">Add a public webpage, ask a question, and get an answer grounded in its content.</p>',
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown("### Settings")
    api_key = st.text_input(
        "OpenAI API key",
        value=os.getenv("OPENAI_API_KEY", ""),
        type="password",
        help="Used only for this app session. You can also set OPENAI_API_KEY in your environment.",
    ).strip()
    st.caption("Your key is sent to OpenAI to generate answers. Never share it publicly.")
    st.markdown("---")
    st.markdown("**Model**")
    st.caption("GPT-4o mini")

if "documents" not in st.session_state:
    st.session_state.documents = []
if "loaded_url" not in st.session_state:
    st.session_state.loaded_url = ""
if "answer" not in st.session_state:
    st.session_state.answer = ""
if "last_question" not in st.session_state:
    st.session_state.last_question = ""

with st.form("webpage_question_form"):
    url = st.text_input(
        "Webpage URL",
        value=st.session_state.loaded_url,
        placeholder="https://example.com/article",
    ).strip()
    question = st.text_area(
        "What would you like to know?",
        placeholder="Summarize the main ideas...",
        height=100,
    ).strip()
    submitted = st.form_submit_button("Load page and ask", type="primary", use_container_width=True)

if submitted:
    parsed_url = urlparse(url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        st.error("Enter a complete webpage URL starting with http:// or https://.")
    elif not question:
        st.error("Enter a question about the webpage.")
    elif not api_key:
        st.error("Add your OpenAI API key in Settings before asking a question.")
    else:
        try:
            if st.session_state.loaded_url != url or not st.session_state.documents:
                with st.spinner("Reading the webpage..."):
                    loader = WebBaseLoader(
                        url,
                        header_template={
                            "User-Agent": os.getenv(
                                "USER_AGENT",
                                "Mozilla/5.0 (compatible; WebpageQABot/1.0)",
                            )
                        },
                    )
                    documents = loader.load()
                if not documents:
                    st.error("No readable content was found at that URL.")
                else:
                    st.session_state.documents = documents
                    st.session_state.loaded_url = url

            if st.session_state.documents and st.session_state.loaded_url == url:
                llm = ChatOpenAI(
                    model="gpt-4o-mini",
                    temperature=0,
                    api_key=api_key,
                )
                prompt = ChatPromptTemplate.from_template(
                    """Answer the question using only the information provided below.
If the answer is not in the webpage content, say you could not find it there.

Context:
{context}

Question:
{input}"""
                )
                document_chain = create_stuff_documents_chain(llm, prompt)
                with st.spinner("Finding an answer..."):
                    answer = document_chain.invoke(
                        {
                            "input": question,
                            "context": st.session_state.documents,
                        }
                    )
                st.session_state.answer = answer
                st.session_state.last_question = question
        except Exception as exc:
            st.error(f"Could not process this webpage or question: {exc}")

if st.session_state.answer:
    st.markdown("### Answer")
    st.markdown(f"**{st.session_state.last_question}**")
    st.markdown(st.session_state.answer)

    with st.expander("Source page"):
        st.markdown(f"[{st.session_state.loaded_url}]({st.session_state.loaded_url})")
        st.caption(f"Read {len(st.session_state.documents)} page document(s).")
