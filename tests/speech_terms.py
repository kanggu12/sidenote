"""Pick from text: the technical terms found in a pasted job posting, resume or notes (server/terms.py), on made-up texts in
Korean and in English: which words are terms by how they are written, two words as one name, the stoplist, a word in other
capitals, the order and the limits, a text with nothing technical, a text past the size the server reads in no more time than
a short one, and which terms the built-in lists or Extra terms hold already.

    .venv/bin/python tests/speech_terms.py
"""
import os
import re
import sys
import tempfile
import time
from pathlib import Path

os.environ.update(SIDENOTE_ANALYZER="mock", SIDENOTE_TRANSCRIBER="null", SIDENOTE_LOG_DIR=tempfile.mkdtemp(prefix="sidenote-terms-"))
ROOT = Path(__file__).resolve().parent.parent   # the repository: this file is in tests/
sys.path.insert(0, str(ROOT))

from server import terms                                    # noqa: E402
from server.config import WHISPER_HINTS                     # noqa: E402
from server.settings import WORD_MAX, WORDS_MAX             # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'ok' if ok else 'FAIL'} {name}" + (f": {str(detail)[:400]}" if detail != "" and not ok else ""))


def words(text):
    """The terms found, as written, in their order."""
    return [w for w, _ in terms.find(text)]


def counts(text):
    """The terms found, each with how many times it appears."""
    return dict(terms.find(text))


# A job posting in Korean, the terms in Latin letters inside its sentences, as postings write them. Made up, as every text here
KO_POSTING = """[가상랩스] ML 플랫폼 엔지니어 채용

주요 업무
- Kubernetes 기반 LLM 서빙 플랫폼(vLLM, TensorRT-LLM) 설계와 운영
- LangGraph로 에이전트 워크플로를 만들고 n8n과 연동합니다
- GitHub Actions와 Argo CD로 CI/CD 파이프라인을 운영합니다
- Apache Kafka, Redis, PostgreSQL 기반 데이터 파이프라인 운영

자격 요건
- Python, Go 중 하나 이상에 능숙하신 분
- AWS(EKS, S3) 또는 GCP 운영 경험 3년 이상
- K8s 클러스터에서 HPA와 Karpenter로 오토스케일링을 해 보신 분

우대 사항
- H100, A100 GPU 클러스터 운영 경험
- pandas, numpy로 데이터를 다뤄 보신 분
- RAG 파이프라인과 LangGraph 경험
- 영어 커뮤니케이션 가능 (business level)

근무지: 서울 강남구 (Seoul, Korea)
지원: careers@example.com / https://example.com/jobs/123
"""

EN_POSTING = """Senior Platform Engineer, Machine Learning Infrastructure

About the role
You will build and run the platform our research teams train and serve models on. Our stack is Kubernetes on AWS, with
Terraform for infrastructure and GitHub Actions for CI/CD.

What you will do
- Operate GPU clusters (H100) with Slurm and Kubernetes
- Build serving with vLLM and Triton, and agents with LangGraph
- Keep Apache Kafka and PostgreSQL healthy at scale

Requirements
- 5+ years of experience with Python or Go
- Strong knowledge of Linux, Docker and networking (TCP/IP, gRPC)
- Experience with C++ or Rust is a plus

Nice to have
- Experience with Ray, MLflow or Kubeflow
- Familiarity with RAG and LLM evaluation

Location: Seoul, Korea (hybrid). Apply at https://example.com/apply or jobs@example.com.
"""

EN_RESUME = """Jamie Doe
Backend Engineer · jamie.doe@example.com · github.com/jamie-doe

Summary
Backend engineer with 6 years of building APIs in Go and Python. Moved a monolith to microservices on Kubernetes.

Experience
Example Corp — Senior Backend Engineer (2021–present)
- Designed an event pipeline on Apache Kafka handling 2M events/day
- Cut p99 latency by 40% with Redis caching and gRPC
- Ran PostgreSQL 15 with logical replication; wrote Terraform modules for AWS (EKS, RDS, S3)
Sample Startup — Software Engineer (2018–2021)
- Built a Django REST API and Celery workers; deployed with Docker and GitHub Actions

Skills
Go, Python, TypeScript, Node.js
Kubernetes, Helm, Argo CD, Prometheus, Grafana
PostgreSQL, Redis, Kafka, ClickHouse

Education
B.S. in Computer Science
"""

KO_RESUME = """경력 요약
백엔드 개발자, 5년. Spring Boot와 Kotlin으로 결제 API를 만들었고, MySQL에서 PostgreSQL로 옮겼습니다.

주요 프로젝트
가상페이 정산 시스템 (2022~2024)
- Spring Boot, JPA, QueryDSL로 정산 배치를 다시 짰습니다
- Redis 캐시로 응답 시간을 120ms에서 30ms로 줄였습니다
- Kafka 컨슈머 랙을 Grafana 대시보드로 지켜봤습니다
- k8s 위에서 helm 차트로 배포, kubectl로 운영

기술
Java, Kotlin, Spring Boot, JPA, MySQL, PostgreSQL, Redis, Kafka, Docker, Kubernetes(K8s), AWS(EC2, RDS)
"""

print("[a job posting in Korean, the terms in Latin letters]")
found = words(KO_POSTING)
want = ["Kubernetes", "LLM", "vLLM", "TensorRT-LLM", "LangGraph", "n8n", "GitHub Actions", "Argo CD", "CI/CD", "Apache Kafka",
        "Redis", "PostgreSQL", "Python", "Go", "AWS", "EKS", "S3", "GCP", "K8s", "HPA", "Karpenter", "H100", "A100", "GPU", "RAG"]
check("every term of it is found, as it is written", not [w for w in want if w not in found], [w for w in want if w not in found])
check("...the one said twice first, with its count", found[0] == "LangGraph" and counts(KO_POSTING)["LangGraph"] == 2, found[:3])
check("lowercase names beside Korean are terms (pandas, numpy)", "pandas" in found and "numpy" in found, found)
gone = ["business", "level", "Seoul", "Korea", "careers", "example.com", "jobs", "123", "3", "ML 플랫폼"]
check("...and not the English words of a sentence, the place, the address or a number", not [w for w in gone if w in found],
      [w for w in gone if w in found])
check("two words as one name: GitHub Actions, Argo CD, Apache Kafka; their halves are no terms of their own",
      not {"GitHub", "Actions", "Argo", "CD", "Apache", "Kafka"} & set(found), found)
check("two technical shapes in a row are two terms (A100 GPU)", "A100 GPU" not in found and "A100" in found and "GPU" in found, found)

print("\n[a job posting in English]")
found = words(EN_POSTING)
want = ["Kubernetes", "AWS", "Terraform", "GitHub Actions", "CI/CD", "GPU", "H100", "Slurm", "vLLM", "Triton", "LangGraph",
        "Apache Kafka", "PostgreSQL", "Python", "Go", "Linux", "Docker", "TCP/IP", "gRPC", "C++", "Rust", "Ray", "MLflow",
        "Kubeflow", "RAG", "LLM"]
check("every term of it is found", not [w for w in want if w not in found], [w for w in want if w not in found])
check("a capitalized name inside a sentence is a term, said twice is counted twice", counts(EN_POSTING).get("Kubernetes") == 2,
      counts(EN_POSTING))
gone = ["Senior", "Platform", "Engineer", "Machine", "Learning", "Infrastructure", "About", "You", "Our", "What", "Operate", "Build",
        "Keep", "Requirements", "Strong", "Experience", "Nice", "Familiarity", "Location", "Seoul", "Korea", "Apply", "Operate GPU"]
check("...and no capital at the head of a sentence or a line, in a title, or of the stoplist", not [w for w in gone if w in found],
      [w for w in gone if w in found])
check("the e-mail address and the web address are no terms", not [w for w in found if "example" in w.lower() or "apply" in w.lower()],
      found)

print("\n[a resume in English]")
found = words(EN_RESUME)
want = ["API", "Go", "Python", "Kubernetes", "Kafka", "Redis", "PostgreSQL", "p99", "gRPC", "Terraform", "AWS", "EKS", "RDS", "S3",
        "Django", "REST", "Celery", "Docker", "GitHub Actions", "TypeScript", "Node.js", "Helm", "Argo CD", "Prometheus", "Grafana",
        "ClickHouse"]
check("every term of it is found", not [w for w in want if w not in found], [w for w in want if w not in found])
check("an abbreviation's plural is the abbreviation, counted with it (APIs, API)", counts(EN_RESUME).get("API") == 2
      and "APIs" not in found, counts(EN_RESUME))
gone = ["Jamie", "Doe", "Jamie Doe", "Summary", "Moved", "Designed", "Cut", "Cut p99", "Ran", "Built", "Startup", "Skills",
        "Education", "B.S", "Computer", "Science", "github.com", "2M"]
check("...and not the person's name, the headings, a line's first verb, the degree or the address", not [w for w in gone if w in found],
      [w for w in gone if w in found])
check("a second word written apart elsewhere makes no name (Apache Kafka, with Kafka in the skills)",
      "Apache Kafka" not in found and counts(EN_RESUME).get("Kafka") == 2, found)

print("\n[a resume in Korean]")
found = words(KO_RESUME)
check("a name of two words, said three times, first, as one term", terms.find(KO_RESUME)[0] == ("Spring Boot", 3), terms.find(KO_RESUME)[:2])
want = ["Kotlin", "API", "MySQL", "PostgreSQL", "JPA", "QueryDSL", "Redis", "Kafka", "Grafana", "helm", "kubectl", "Java", "Docker",
        "Kubernetes", "AWS", "EC2", "RDS"]
check("every term of it is found, a lowercase one beside Korean too (helm, kubectl)", not [w for w in want if w not in found],
      [w for w in want if w not in found])
check("K8s and k8s are one term", counts(KO_RESUME).get("k8s", 0) + counts(KO_RESUME).get("K8s", 0) == 2
      and not ("k8s" in found and "K8s" in found), found)
check("numbers with units and years are no terms", not {"120ms", "30ms", "2022", "2024", "5"} & set(found), found)

print("\n[a posting's culture and perks, in English inside a Korean posting]")
BOILERPLATE = """About Us
가상랩스는 LLM 기반 B2B SaaS를 만드는 팀입니다. Series A 투자를 받았고 Remote First로 일합니다.

Who We Are Looking For
- Python, FastAPI로 API를 설계해 보신 분

Our Values
- Ownership
- Transparency

Benefits
- MacBook Pro 지급, 점심 제공, Flexible Hours, Work from Anywhere
서류 → Coding Test → 1차 인터뷰 → Culture Fit → 처우 협의
"""
found = words(BOILERPLATE)
check("the terms of it are found", {"LLM", "SaaS", "Python", "FastAPI", "API"} <= set(found), found)
gone = ["First", "Remote First", "Looking", "Ownership", "Transparency", "Flexible Hours", "Flexible", "Hours", "Anywhere", "Fit",
        "Culture Fit", "Series", "Values", "Benefits", "About", "Coding Test"]
check("...and not the words of its culture and perks, beside Korean, in a list or alone on a line", not [w for w in gone if w in found],
      [w for w in gone if w in found])

print("\n[how a term is written]")
shapes = "Built with C++, C#, F# and .NET; CI/CD in TensorRT-LLM; served by Node.js and llama.cpp; n8n, K8s, S3 and H100 too."
found = words(shapes)
want = ["C++", "C#", "F#", ".NET", "CI/CD", "TensorRT-LLM", "Node.js", "llama.cpp", "n8n", "K8s", "S3", "H100"]
check("a mark inside or at the end, and letters with digits", found == want, found)
check("an inner capital and all capitals of 2 to 10 letters", words("using LangGraph, PostgreSQL, gRPC, MLOps, AWS, HPA and NVIDIA")
      == ["LangGraph", "PostgreSQL", "gRPC", "MLOps", "AWS", "HPA", "NVIDIA"], words("using LangGraph, PostgreSQL, gRPC, MLOps, AWS, HPA and NVIDIA"))
check("...but no shout of more than ten capitals", words("with RESPONSIBILITIES and AWS") == ["AWS"], words("with RESPONSIBILITIES and AWS"))
noise = ("In 2024, call 010-1234-5678 or mail hr@example.com, see https://example.com/jobs and www.example.org, "
         "with 16GB, 100ms, 3x, 5+, 1st, 4K, v1.2.3, Q3, example.com, e.g. and i.e. too.")
check("numbers alone, years, phone numbers, e-mail and web addresses, domains, numbers with units, versions: none",
      words(noise) == [], words(noise))
check("a name shaped like a domain stays (Node.js, ASP.NET, Socket.IO), an address does not (github.io)",
      words("with Node.js, ASP.NET, Socket.IO and github.io") == ["Node.js", "ASP.NET", "Socket.IO"],
      words("with Node.js, ASP.NET, Socket.IO and github.io"))
check("3D, 5G and 2FA are terms, not numbers with a unit", words("with 3D, 5G and 2FA") == ["3D", "5G", "2FA"], words("with 3D, 5G and 2FA"))
check("a plain word inside a hyphen goes and the technical part stays (AI-driven, multi-GPU); end-to-end is nothing",
      words("our AI-driven, multi-GPU and end-to-end real-time stack") == ["AI", "GPU"],
      words("our AI-driven, multi-GPU and end-to-end real-time stack"))
check("names joined by a slash are each a term (AWS/GCP/Azure, Python/Go), a compound stays one (CI/CD, TCP/IP, UI/UX)",
      words("on AWS/GCP/Azure in Python/Go with CI/CD, TCP/IP and UI/UX") == ["AWS", "GCP", "Azure", "Python", "Go", "CI/CD", "TCP/IP", "UI/UX"],
      words("on AWS/GCP/Azure in Python/Go with CI/CD, TCP/IP and UI/UX"))
check("a name from code is no term (MAX_BODY, snake_case), nor a file (README.md, index.html)",
      words("set MAX_BODY in snake_case_names, see README.md and index.html") == [], words("set MAX_BODY in snake_case_names, see README.md and index.html"))
check("a capital after an abbreviation's dot stands inside the sentence (e.g. Kafka), and after a bracket",
      words("message queues (e.g. RabbitMQ, NATS) and caches (Memcached)") == ["RabbitMQ", "NATS", "Memcached"],
      words("message queues (e.g. RabbitMQ, NATS) and caches (Memcached)"))
check("a capital at the head of a line goes on from a long line that ended mid-sentence (a PDF's lines)",
      words("Over the last three years I ran our data platform on\nKubernetes and moved the jobs to\nDagster") == ["Kubernetes", "Dagster"],
      words("Over the last three years I ran our data platform on\nKubernetes and moved the jobs to\nDagster"))
check("a skill alone on its line, and a list after a colon, are terms", words("Skills\n- Terraform\nLanguages: Python, Go")
      == ["Terraform", "Python", "Go"], words("Skills\n- Terraform\nLanguages: Python, Go"))
check("a past tense heading a title is no term (Distributed Systems, Embedded Linux), and the name after it is",
      words("worked on Distributed Systems with Embedded Linux") == ["Linux"], words("worked on Distributed Systems with Embedded Linux"))

print("\n[two words as one name]")
check("a technical shape and a word: GitHub Actions, AWS Lambda", words("deployed by GitHub Actions to AWS Lambda")
      == ["GitHub Actions", "AWS Lambda"], words("deployed by GitHub Actions to AWS Lambda"))
check("two capitalized words in a sentence: Apache Kafka, Spring Boot", words("we run Apache Kafka and Spring Boot")
      == ["Apache Kafka", "Spring Boot"], words("we run Apache Kafka and Spring Boot"))
check("...and at a sentence's head when it goes on", words("Apache Kafka is our backbone.") == ["Apache Kafka"],
      words("Apache Kafka is our backbone."))
check("two technical shapes are two terms (AWS EKS)", words("on AWS EKS") == ["AWS", "EKS"], words("on AWS EKS"))
check("a person's name or a title alone on its line is no name", words("Jordan Rivers\nStaff Engineer\nwith Go") == ["Go"],
      words("Jordan Rivers\nStaff Engineer\nwith Go"))
check("a word written alone elsewhere is a term of its own, and the word before it too (Apache, Kafka)",
      terms.find("we run Apache Kafka and watch Kafka lag") == [("Kafka", 2), ("Apache", 1)],
      terms.find("we run Apache Kafka and watch Kafka lag"))

print("\n[the stoplist]")
common = ["Team", "Project", "Experience", "Developed", "Required", "Korea", "Seoul"]
said = "we need " + ", ".join(common) + " and Kafka"
check("the words every posting or resume has are left out, in a sentence and in a list", words(said) == ["Kafka"], words(said))
check("...however they are written", words("with TEAM, project, EXPERIENCE 경험과 project 관리") == [], words("with TEAM, project, EXPERIENCE 경험과 project 관리"))
check("each of them is in the stoplist or a past tense", all(terms.common(w) for w in common), [w for w in common if not terms.common(w)])
check("the function words of a sentence beside Korean are no terms", words("영어 가능자 (and the team for business level)") == [],
      words("영어 가능자 (and the team for business level)"))

print("\n[a word in other capitals]")
check("the same word in other capitals is one term, written as it is written most often",
      terms.find("Kafka를 쓰고 kafka 토픽을 보고 Kafka 컨슈머와 KAFKA") == [("Kafka", 4)], terms.find("Kafka를 쓰고 kafka 토픽을 보고 Kafka 컨슈머와 KAFKA"))
check("...and of two ways as often, the first", terms.find("k8s 클러스터와 K8s 노드") == [("k8s", 2)], terms.find("k8s 클러스터와 K8s 노드"))
check("a lowercase word away from Korean is no term, and counts for none (go to market, Go)",
      terms.find("we go to market with Go") == [("Go", 1)], terms.find("we go to market with Go"))

print("\n[order and limits]")
check("the most frequent first, then the first to appear", words("with Zeta, Alpha, Beta, Alpha and Beta, Gamma 3")
      == ["Alpha", "Beta", "Zeta", "Gamma"], words("with Zeta, Alpha, Beta, Alpha and Beta, Gamma 3"))
many = " ".join(f"with Tool{i}" for i in range(100))
check(f"at most {terms.TERMS_MAX} terms, the first {terms.TERMS_MAX} of those said as often",
      len(terms.find(many)) == terms.TERMS_MAX == 60 and words(many)[:3] == ["Tool0", "Tool1", "Tool2"], len(terms.find(many)))
long_word = "Very" + "Long" * 15                 # 64 letters: past the most an Extra term may hold
check(f"a word longer than an Extra term may be ({WORD_MAX}) is no term", words(f"with {long_word} and Kafka") == ["Kafka"],
      words(f"with {long_word} and Kafka"))
check("a term of two words is never longer than one may be either", all(len(w) <= WORD_MAX for w in words(KO_POSTING + EN_POSTING)))
check("every term fits the setting's own rules (no comma, no space round it)", all("," not in w and w == w.strip()
      for w in words(KO_POSTING + EN_POSTING + EN_RESUME + KO_RESUME)))
check(f"more terms are offered than Extra terms hold ({WORDS_MAX}), so some can be passed over", terms.TERMS_MAX > WORDS_MAX)
check("the most a text may hold is 64 KB", terms.TEXT_MAX == 64 * 1024)
copy = re.search(r"const TERMS_TEXT_MAX = (\d+) \* (\d+);", (ROOT / "panel" / "app.js").read_text(encoding="utf-8"))
check("...and the panel checks the same before it sends one (panel/app.js, TERMS_TEXT_MAX)",
      bool(copy) and int(copy[1]) * int(copy[2]) == terms.TEXT_MAX, copy and copy.group())

print("\n[nothing technical]")
check("a Korean text with nothing technical has no terms",
      words("오늘은 날씨가 좋네요. 내일 다시 이야기해요. 2024년 3월 5일에 만나요.") == [], words("오늘은 날씨가 좋네요. 내일 다시 이야기해요."))
check("an English one neither", words("Thanks for your time today. We will get back to you within a week.") == [],
      words("Thanks for your time today. We will get back to you within a week."))
check("nor an empty one", terms.find("") == [] and terms.find("   \n\n ") == [])

print("\n[a text as long as the server reads, in no more time than it should]")
# A run of letters as long as a text may be: an address was looked for from each letter of it, reading the rest of the run each
# time, and 64 KB of them took seconds. Each of these is read in a fraction of that
for name, text in (("letters", "a" * terms.TEXT_MAX), ("addresses", "a@" * (terms.TEXT_MAX // 2)), ("words", "with Kafka " * 5900),
                   ("a long posting", (KO_POSTING + EN_POSTING + EN_RESUME + KO_RESUME) * 20)):
    began = time.perf_counter()
    terms.find(text[:terms.TEXT_MAX])
    took = time.perf_counter() - began
    check(f"{name}: {len(text[:terms.TEXT_MAX].encode())} bytes in {took:.2f} s, under 2 s on a busy PC", took < 2.0, f"{took:.2f} s")

print("\n[what the built-in lists and Extra terms hold already]")
marked = terms.marked(terms.find("Kubernetes 위에서 LangGraph와 Zabbix, kafka를 씁니다"), WHISPER_HINTS, ["zabbix"])
by = {m["word"]: m for m in marked}
check("each term with its count and two marks", all(set(m) == {"word", "count", "listed", "have"} for m in marked), marked)
check("listed: in the built-in lists of either language, in any capitals", by["Kubernetes"]["listed"] and by["LangGraph"]["listed"]
      and by["kafka"]["listed"] and not by["Zabbix"]["listed"], marked)
check("have: in Extra terms, in any capitals", by["Zabbix"]["have"] and not by["Kubernetes"]["have"], marked)
check("with the built-in hints off, nothing is listed", not any(m["listed"] for m in terms.marked(terms.find("on Kubernetes"), {}, [])))
check("the lists are read as the speech prompt reads them, word by word", terms.hint_words({"en": "Helm, KV cache, n8n."})
      == {"helm", "kv cache", "n8n"}, terms.hint_words({"en": "Helm, KV cache, n8n."}))

print(f"\n==== {len(PASS)} passed, {len(FAIL)} failed ====")
sys.exit(1 if FAIL else 0)
