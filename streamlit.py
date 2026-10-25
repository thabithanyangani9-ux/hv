
import os
import io
import sqlite3
import hashlib
import secrets
import streamlit as st
import requests
from openai import OpenAI
from pypdf import PdfReader

st.set_page_config(
    page_title="School E-Learning System",
    page_icon="🎓",
    layout="wide"
)

DB_PATH = os.getenv("DB_PATH", "school.db")


# ---------- DATABASE ----------
def connect_db():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db():
    with connect_db() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                subject TEXT,
                content TEXT,
                uploaded_by TEXT
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS quiz_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT,
                quiz_name TEXT,
                score INTEGER,
                total INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), 200000
    ).hex()
    return f"{salt}${hashed}"


def verify_password(password, stored):
    try:
        salt, expected = stored.split("$", 1)
        return secrets.compare_digest(
            hash_password(password, salt).split("$", 1)[1],
            expected
        )
    except (ValueError, AttributeError):
        return False


def create_user(username, password, role):
    with connect_db() as con:
        con.execute(
            "INSERT INTO users VALUES (?, ?, ?)",
            (username, hash_password(password), role)
        )


def get_user(username):
    with connect_db() as con:
        return con.execute(
            "SELECT username, password_hash, role "
            "FROM users WHERE username = ?",
            (username,)
        ).fetchone()


init_db()


# ---------- FIRST ADMIN ----------
# Set these two environment variables before starting the app.
# The initial administrator is created only if the user table is empty.
if os.getenv("INITIAL_ADMIN_USER") and os.getenv("INITIAL_ADMIN_PASSWORD"):
    if not get_user(os.environ["INITIAL_ADMIN_USER"]):
        with connect_db() as con:
            empty = con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
        if empty:
            create_user(
                os.environ["INITIAL_ADMIN_USER"],
                os.environ["INITIAL_ADMIN_PASSWORD"],
                "admin"
            )


# ---------- LOGIN ----------
if "user" not in st.session_state:
    st.session_state.user = None
if "role" not in st.session_state:
    st.session_state.role = None

if not st.session_state.user:
    st.title("🎓 School E-Learning System")
    login_tab, register_tab = st.tabs(["Sign in", "Register student"])

    with login_tab:
        username = st.text_input("Username", key="login_user")
        password = st.text_input("Password", type="password", key="login_pass")
        if st.button("Sign in", type="primary"):
            user = get_user(username.strip())
            if user and verify_password(password, user[1]):
                st.session_state.user = user[0]
                st.session_state.role = user[2]
                st.rerun()
            else:
                st.error("Incorrect username or password.")

    with register_tab:
        st.info("Student self-registration creates student accounts only.")
        new_user = st.text_input("Choose a username", key="new_user")
        new_pass = st.text_input("Choose a password", type="password", key="new_pass")
        confirm = st.text_input("Confirm password", type="password")
        if st.button("Create student account"):
            if not new_user.strip() or len(new_pass) < 10:
                st.error("Enter a username and a password of at least 10 characters.")
            elif new_pass != confirm:
                st.error("Passwords do not match.")
            elif get_user(new_user.strip()):
                st.error("That username already exists.")
            else:
                create_user(new_user.strip(), new_pass, "student")
                st.success("Account created. Sign in above.")

    st.stop()


username = st.session_state.user
role = st.session_state.role

st.sidebar.title("School Learning")
st.sidebar.write(f"User: **{username}**")
st.sidebar.write(f"Role: **{role.title()}**")

if st.sidebar.button("Log out"):
    st.session_state.user = None
    st.session_state.role = None
    st.rerun()


# ---------- NAVIGATION ----------
pages = ["Dashboard", "Search Engine", "E-Lab", "AI Code Generator"]

if role in ("teacher", "admin"):
    pages += ["Manage Library", "Quiz Progress"]

if role == "admin":
    pages += ["User Management"]

page = st.sidebar.radio("Open module", pages)

st.title("🎓 School Learning System")


# ---------- DASHBOARD ----------
if page == "Dashboard":
    st.subheader("Welcome to your learning workspace")
    c1, c2, c3 = st.columns(3)
    c1.metric("Role", role.title())
    with connect_db() as con:
        docs = con.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        results = con.execute(
            "SELECT COUNT(*) FROM quiz_results WHERE username = ?",
            (username,)
        ).fetchone()[0]
    c2.metric("Library resources", docs)
    c3.metric("Your quiz attempts", results)

    st.write("Use the menu on the left to search, study, complete quizzes or generate code.")


# ---------- SEARCH ENGINE ----------
elif page == "Search Engine":
    st.subheader("🔎 Search the internet and school library")
    query = st.text_input("Enter a topic, question or keyword")

    search_mode = st.radio(
        "Search in",
        ["Both", "Internet", "School documents"],
        horizontal=True
    )

    if st.button("Search", type="primary") and query.strip():
        if search_mode in ("Both", "School documents"):
            terms = [word.lower() for word in query.split() if len(word) > 1]
            with connect_db() as con:
                rows = con.execute(
                    "SELECT filename, subject, content FROM documents"
                ).fetchall()

            found = [
                row for row in rows
                if any(term in ((row[0] or "") + " " +
                                (row[1] or "") + " " +
                                (row[2] or "")).lower()
                       for term in terms)
            ]

            st.markdown("### School library results")
            if found:
                for filename, subject, content in found:
                    with st.expander(f"{filename} — {subject or 'General'}"):
                        st.write((content or "")[:3000])
            else:
                st.info("No matching school documents found.")

        if search_mode in ("Both", "Internet"):
            api_key = os.getenv("BRAVE_API_KEY")
            st.markdown("### Internet results")
            if not api_key:
                st.warning("Set BRAVE_API_KEY in your environment to enable internet search.")
            else:
                try:
                    response = requests.get(
                        "https://api.search.brave.com/res/v1/web/search",
                        headers={"X-Subscription-Token": api_key},
                        params={"q": query, "count": 10},
                        timeout=20
                    )
                    response.raise_for_status()
                    results = response.json().get("web", {}).get("results", [])
                    for item in results:
                        st.markdown(f"**[{item.get('title', 'Result')}]({item.get('url', '')})**")
                        st.write(item.get("description", ""))
                except requests.RequestException as exc:
                    st.error(f"Search failed: {exc}")


# ---------- E-LAB ----------
elif page == "E-Lab":
    st.subheader("📚 Digital learning laboratory")
    lab_tabs = st.tabs([
        "Books and PDFs", "Text-to-speech",
        "Quizzes", "Programming lessons"
    ])

    with lab_tabs[0]:
        with connect_db() as con:
            docs = con.execute(
                "SELECT id, filename, subject, content FROM documents ORDER BY id DESC"
            ).fetchall()

        if docs:
            for doc_id, filename, subject, content in docs:
                st.write(f"**{filename}** — {subject or 'General'}")
                st.text((content or "")[:500])
        else:
            st.info("No books have been uploaded yet. Ask a teacher to add resources.")

        uploaded = st.file_uploader("Upload a PDF for personal reading", type=["pdf"])
        if uploaded:
            try:
                reader = PdfReader(io.BytesIO(uploaded.getvalue()))
                text_content = "\n".join(
                    page.extract_text() or "" for page in reader.pages
                )
                st.download_button(
                    "Download PDF",
                    uploaded.getvalue(),
                    file_name=uploaded.name,
                    mime="application/pdf"
                )
                st.text_area("Extracted PDF text", text_content, height=250)
            except Exception as exc:
                st.error(f"Could not read PDF: {exc}")

    with lab_tabs[1]:
        speech_text = st.text_area("Text to read aloud", height=180)
        st.caption("Uses your browser's speech synthesis. Available voices depend on the device.")
        if speech_text:
            import json
            safe_text = json.dumps(speech_text)
            st.components.v1.html(
                f"""
                <button onclick='speakText()'>🔊 Read aloud</button>
                <button onclick='window.speechSynthesis.cancel()'>Stop</button>
                <script>
                const textToRead = {safe_text};
                function speakText() {{
                    window.speechSynthesis.cancel();
                    const utterance = new SpeechSynthesisUtterance(textToRead);
                    const voices = window.speechSynthesis.getVoices();
                    const selector = document.getElementById("voice");
                    if (selector && voices[selector.value]) {{
                        utterance.voice = voices[selector.value];
                    }}
                    window.speechSynthesis.speak(utterance);
                }}
                </script>
                <label>Voice: </label><select id="voice"></select>
                <script>
                function loadVoices() {{
                    const select = document.getElementById("voice");
                    select.innerHTML = "";
                    window.speechSynthesis.getVoices().forEach((voice, i) => {{
                        const option = document.createElement("option");
                        option.value = i;
                        option.textContent = voice.name + " (" + voice.lang + ")";
                        select.appendChild(option);
                    }});
                }}
                loadVoices();
                window.speechSynthesis.onvoiceschanged = loadVoices;
                </script>
                """,
                height=130
            )

    with lab_tabs[2]:
        st.write("### Python basics quiz")
        questions = [
            ("Which symbol starts a comment in Python?", ["//", "#", "<!--"], 1),
            ("Which type stores True or False?", ["bool", "str", "list"], 0),
            ("Which keyword defines a function?", ["func", "define", "def"], 2),
        ]
        answers = []
        for i, (question, options, correct) in enumerate(questions):
            answers.append(st.radio(question, options, key=f"quiz_{i}"))

        quiz_name = "Python basics"
        if st.button("Submit quiz"):
            score = sum(
                answers[i] == questions[i][1][questions[i][2]]
                for i in range(len(questions))
            )
            with connect_db() as con:
                con.execute(
                    "INSERT INTO quiz_results (username, quiz_name, score, total) "
                    "VALUES (?, ?, ?, ?)",
                    (username, quiz_name, score, len(questions))
                )
            st.success(f"Your score: {score}/{len(questions)}")

    with lab_tabs[3]:
        st.markdown("""
        ### Python programming lessons

        **Lesson 1: Variables**
        ```python
        student_name = "Tariro"
        form = 2
        print(student_name, form)
        ```

        **Lesson 2: Conditions**
        ```python
        mark = 75
        if mark >= 50:
            print("Pass")
        else:
            print("Try again")
        ```

        **Lesson 3: Loops**
        ```python
        for number in range(1, 6):
            print(number)
        ```
        """)


# ---------- AI CODE GENERATOR ----------
elif page == "AI Code Generator":
    st.subheader("🤖 AI programming assistant")
    st.caption("Generated code may contain mistakes. Review and test it before using it.")

    if role not in ("student", "teacher", "admin"):
        st.error("You do not have permission to use this module.")
        st.stop()

    task = st.text_area(
        "Describe what you want the AI to create, explain or fix",
        placeholder="Example: Write Python code for a student attendance tracker."
    )
    language = st.selectbox(
        "Programming language",
        ["Python", "HTML", "CSS", "JavaScript", "Java", "SQL", "C++"]
    )
    operation = st.selectbox(
        "Action", ["Generate code", "Explain code", "Fix code"]
    )
    existing_code = ""
    if operation != "Generate code":
        existing_code = st.text_area("Paste your code here", height=180)

    if st.button("Ask AI", type="primary"):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            st.error("Set OPENAI_API_KEY in your environment first.")
        elif not task.strip():
            st.warning("Describe the task first.")
        else:
            try:
                client = OpenAI(api_key=api_key)
                prompt = (
                    f"Action: {operation}\nLanguage: {language}\n"
                    f"User request: {task}\n"
                    f"Existing code:\n{existing_code}\n\n"
                    "Provide educational, safe, well-commented assistance. "
                    "For code generation, include a complete example. "
                    "For code fixes, explain the changes. Never claim the code "
                    "was executed or tested unless it actually was."
                )
                with st.spinner("Generating response..."):
                    result = client.responses.create(
                        model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
                        input=prompt
                    )
                st.markdown("### AI response")
                st.markdown(result.output_text)
                st.download_button(
                    "Download response as text",
                    result.output_text,
                    file_name="ai_code_response.txt",
                    mime="text/plain"
                )
            except Exception as exc:
                st.error(f"AI request failed: {exc}")


# ---------- MANAGE LIBRARY ----------
elif page == "Manage Library":
    if role not in ("teacher", "admin"):
        st.error("Permission denied.")
        st.stop()

    st.subheader("📂 Manage school library")
    uploaded = st.file_uploader(
        "Upload a PDF for the school library",
        type=["pdf"],
        key="library_pdf"
    )
    subject = st.text_input("Subject or category")

    if st.button("Add to school library"):
        if not uploaded:
            st.warning("Select a PDF first.")
        else:
            try:
                reader = PdfReader(io.BytesIO(uploaded.getvalue()))
                content = "\n".join(
                    page.extract_text() or "" for page in reader.pages
                )
                with connect_db() as con:
                    con.execute(
                        "INSERT INTO documents "
                        "(filename, subject, content, uploaded_by) VALUES (?, ?, ?, ?)",
                        (uploaded.name, subject, content, username)
                    )
                st.success("PDF indexed in the school library.")
            except Exception as exc:
                st.error(f"Could not process PDF: {exc}")

    st.caption("This starter stores extracted text, not the original PDF. Use persistent file storage for downloadable school books.")


# ---------- QUIZ PROGRESS ----------
elif page == "Quiz Progress":
    if role not in ("teacher", "admin"):
        st.error("Permission denied.")
        st.stop()

    st.subheader("📈 Quiz progress")
    with connect_db() as con:
        rows = con.execute(
            "SELECT username, quiz_name, score, total, created_at "
            "FROM quiz_results ORDER BY created_at DESC"
        ).fetchall()

    if rows:
        st.dataframe(
            rows,
            column_config={
                "0": "Student",
                "1": "Quiz",
                "2": "Score",
                "3": "Total",
                "4": "Date"
            },
            use_container_width=True
        )
    else:
        st.info("No quiz results yet.")


# ---------- USER MANAGEMENT ----------
elif page == "User Management":
    if role != "admin":
        st.error("Permission denied.")
        st.stop()

    st.subheader("👥 User Management")
    st.write("Create teacher and administrator accounts here.")

    new_username = st.text_input("New username")
    new_password = st.text_input("Temporary password", type="password")
    new_role = st.selectbox("Role", ["teacher", "admin"])

    if st.button("Create account"):
        if not new_username.strip() or len(new_password) < 10:
            st.error("Enter a username and a password of at least 10 characters.")
        elif get_user(new_username.strip()):
            st.error("Username already exists.")
        else:
            create_user(new_username.strip(), new_password, new_role)
            st.success(f"Created {new_role} account.")

    with connect_db() as con:
        user_rows = con.execute(
            "SELECT username, role FROM users ORDER BY username"
        ).fetchall()
    st.dataframe(user_rows, use_container_width=True)
