
import html as _html
import re as _re

SKILLS: dict[str, list[str]] = {
    "Languages": ["Python", "Java", "JavaScript", "TypeScript", "Go", "Golang", "Rust", "C", "C++", "C#", ".NET", "Ruby", "PHP", "Swift", "Kotlin", "Scala", "Bash", "Shell", "PowerShell", "SQL", "R", "MATLAB", "Perl", "Objective-C"],
    "Frontend": ["React", "React.js", "Next.js", "Vue", "Vue.js", "Angular", "Svelte", "Redux", "HTML", "HTML5", "CSS", "CSS3", "Tailwind", "SASS", "SCSS", "Webpack", "Vite", "jQuery"],
    "Backend & Frameworks": ["Django", "Flask", "FastAPI", "Spring", "Spring Boot", "Node.js", "Express", "NestJS", "Rails", "Ruby on Rails", "Laravel", "ASP.NET", "GraphQL", "REST", "gRPC", "Microservices", "Symfony", "Pyramid"],
    "Cloud & Infrastructure": ["AWS", "GCP", "Azure", "Kubernetes", "K8s", "Docker", "Terraform", "Ansible", "Chef", "Puppet", "CloudFormation", "Helm", "Istio", "Lambda", "EC2", "S3", "RDS", "EKS", "AKS", "GKE", "Cloudflare", "Linux", "Unix", "VMware"],
    "DevOps & CI/CD": ["GitHub Actions", "GitLab CI", "Jenkins", "CircleCI", "ArgoCD", "Prometheus", "Grafana", "Datadog", "OpenTelemetry", "Elasticsearch", "Kibana", "Logstash", "Fluentd"],
    "Databases": ["PostgreSQL", "MySQL", "MongoDB", "Redis", "DynamoDB", "Cassandra", "Snowflake", "BigQuery", "Redshift", "SQLite", "Oracle", "MS SQL Server", "MariaDB", "Neo4j", "Elasticsearch", "Couchbase"],
    "Security Testing & Offensive": ["Burp Suite", "Metasploit", "Nmap", "Nikto", "sqlmap", "OWASP ZAP", "ZAP", "Kali Linux", "Fuzzing", "Reverse Engineering", "Malware Analysis"],
    "Detection & SOC": ["Splunk", "QRadar", "Microsoft Sentinel", "ArcSight", "Sumo Logic", "CrowdStrike", "SentinelOne", "Carbon Black", "Snort", "Suricata", "Zeek", "YARA", "Sigma"],
    "IAM & Zero Trust": ["Okta", "Auth0", "Keycloak", "Active Directory", "Entra ID", "LDAP", "SAML", "OAuth", "OpenID Connect", "SSO", "MFA", "CyberArk"],
    "GRC & Compliance": ["ISO 27001", "SOC 2", "GDPR", "HIPAA", "PCI DSS", "NIST", "FedRAMP", "CISM", "CISSP", "CISA", "CRISC"],
    "Cloud Security": ["Prisma Cloud", "Wiz", "Palo Alto", "Check Point", "Fortinet", "HashiCorp Vault"],
    "QA & Testing": ["Selenium", "Cypress", "Playwright", "PyTest", "JUnit", "TestNG", "Jest", "Mocha", "Chai", "Cucumber", "Appium", "Postman", "JMeter", "Gatling", "k6"],
    "Data & ML": ["TensorFlow", "PyTorch", "Keras", "scikit-learn", "Pandas", "NumPy", "Spark", "Hadoop", "Airflow", "Kafka"],
    "Networking": ["TCP/IP", "DNS", "DHCP", "BGP", "OSPF", "VPN", "Firewall", "Wireshark", "tcpdump"],
    "Collaboration & Tools": ["Git", "GitHub", "GitLab", "Bitbucket", "Jira", "Confluence", "Slack", "Agile", "Scrum", "Kanban"],
}

# Curated: specific NAMED tools only — generic concepts (Automation, Compliance,
# QA, IAM, …) match as common words and pollute demand counts.
# Entry: (display, category, [variants]) — variants fold synonyms into one count.
CANON = [
    ("Python", "Languages", ["python"]),
    ("Java", "Languages", ["java"]),
    ("JavaScript", "Languages", ["javascript"]),
    ("TypeScript", "Languages", ["typescript"]),
    ("Go", "Languages", ["golang"]),
    ("Rust", "Languages", ["rust"]),
    ("C++", "Languages", ["c++"]),
    ("C#", "Languages", ["c#"]),
    (".NET", "Languages", [".net"]),
    ("Ruby", "Languages", ["ruby"]),
    ("PHP", "Languages", ["php"]),
    ("Swift", "Languages", ["swift"]),
    ("Kotlin", "Languages", ["kotlin"]),
    ("Scala", "Languages", ["scala"]),
    ("Bash", "Languages", ["bash", "shell scripting"]),
    ("SQL", "Languages", ["sql"]),

    ("React", "Frontend", ["react", "react.js", "reactjs"]),
    ("Next.js", "Frontend", ["next.js"]),
    ("Vue", "Frontend", ["vue", "vue.js", "vuejs"]),
    ("Angular", "Frontend", ["angular"]),
    ("Svelte", "Frontend", ["svelte"]),
    ("Redux", "Frontend", ["redux"]),
    ("Tailwind", "Frontend", ["tailwind"]),
    ("SASS", "Frontend", ["sass", "scss"]),
    ("Webpack", "Frontend", ["webpack"]),
    ("Vite", "Frontend", ["vite"]),

    ("Django", "Backend", ["django"]),
    ("Flask", "Backend", ["flask"]),
    ("FastAPI", "Backend", ["fastapi"]),
    ("Spring", "Backend", ["spring boot"]),
    ("Node.js", "Backend", ["node.js", "nodejs"]),
    ("Express", "Backend", ["express.js", "expressjs"]),
    ("NestJS", "Backend", ["nestjs"]),
    ("Rails", "Backend", ["rails", "ruby on rails"]),
    ("Laravel", "Backend", ["laravel"]),
    ("ASP.NET", "Backend", ["asp.net"]),
    ("GraphQL", "Backend", ["graphql"]),
    ("gRPC", "Backend", ["grpc"]),

    ("AWS", "Cloud & DevOps", ["aws", "amazon web services"]),
    ("GCP", "Cloud & DevOps", ["gcp", "google cloud platform"]),
    ("Azure", "Cloud & DevOps", ["azure", "microsoft azure"]),
    ("Kubernetes", "Cloud & DevOps", ["kubernetes", "k8s"]),
    ("Docker", "Cloud & DevOps", ["docker"]),
    ("Terraform", "Cloud & DevOps", ["terraform"]),
    ("Pulumi", "Cloud & DevOps", ["pulumi"]),
    ("Ansible", "Cloud & DevOps", ["ansible"]),
    ("Puppet", "Cloud & DevOps", ["puppet"]),
    ("CloudFormation", "Cloud & DevOps", ["cloudformation"]),
    ("Helm", "Cloud & DevOps", ["helm"]),
    ("Istio", "Cloud & DevOps", ["istio"]),
    ("Lambda", "Cloud & DevOps", ["aws lambda"]),
    ("GitHub Actions", "Cloud & DevOps", ["github actions"]),
    ("GitLab CI", "Cloud & DevOps", ["gitlab ci"]),
    ("Jenkins", "Cloud & DevOps", ["jenkins"]),
    ("CircleCI", "Cloud & DevOps", ["circleci"]),
    ("ArgoCD", "Cloud & DevOps", ["argocd", "argo-cd"]),
    ("Prometheus", "Cloud & DevOps", ["prometheus"]),
    ("Grafana", "Cloud & DevOps", ["grafana"]),
    ("Datadog", "Cloud & DevOps", ["datadog"]),
    ("OpenTelemetry", "Cloud & DevOps", ["opentelemetry"]),
    ("Linux", "Cloud & DevOps", ["linux"]),
    ("Cloudflare", "Cloud & DevOps", ["cloudflare"]),
    ("VMware", "Cloud & DevOps", ["vmware"]),

    ("PostgreSQL", "Databases", ["postgresql", "postgres"]),
    ("MySQL", "Databases", ["mysql"]),
    ("MongoDB", "Databases", ["mongodb"]),
    ("Redis", "Databases", ["redis"]),
    ("DynamoDB", "Databases", ["dynamodb"]),
    ("Cassandra", "Databases", ["cassandra"]),
    ("Snowflake", "Databases", ["snowflake"]),
    ("BigQuery", "Databases", ["bigquery"]),
    ("Redshift", "Databases", ["redshift"]),
    ("Oracle", "Databases", ["oracle"]),
    ("SQL Server", "Databases", ["sql server", "ms sql server"]),
    ("MariaDB", "Databases", ["mariadb"]),
    ("Neo4j", "Databases", ["neo4j"]),
    ("Elasticsearch", "Databases", ["elasticsearch"]),

    ("Splunk", "Security Tools", ["splunk"]),
    ("CrowdStrike", "Security Tools", ["crowdstrike"]),
    ("SentinelOne", "Security Tools", ["sentinelone"]),
    ("Carbon Black", "Security Tools", ["carbon black"]),
    ("Wireshark", "Security Tools", ["wireshark"]),
    ("Burp Suite", "Security Tools", ["burp suite", "burpsuite"]),
    ("Metasploit", "Security Tools", ["metasploit"]),
    ("Nmap", "Security Tools", ["nmap"]),
    ("Nessus", "Security Tools", ["nessus"]),
    ("OWASP ZAP", "Security Tools", ["owasp zap", "zap"]),
    ("Kali Linux", "Security Tools", ["kali linux", "kali"]),
    ("YARA", "Security Tools", ["yara"]),
    ("Sigma", "Security Tools", ["sigma"]),
    ("Wiz", "Security Tools", ["wiz"]),
    ("Prisma Cloud", "Security Tools", ["prisma cloud"]),
    ("Palo Alto", "Security Tools", ["palo alto"]),
    ("Fortinet", "Security Tools", ["fortinet"]),
    ("HashiCorp Vault", "Security Tools", ["hashicorp vault"]),
    ("Okta", "Security Tools", ["okta"]),
    ("Auth0", "Security Tools", ["auth0"]),
    ("CyberArk", "Security Tools", ["cyberark"]),
    ("Active Directory", "Security Tools", ["active directory"]),
    ("Entra ID", "Security Tools", ["entra id", "azure ad"]),
    ("OAuth", "Security Tools", ["oauth", "oauth2"]),
    ("SAML", "Security Tools", ["saml"]),
    ("CISSP", "Security Tools", ["cissp"]),

    ("TensorFlow", "Data & ML", ["tensorflow"]),
    ("PyTorch", "Data & ML", ["pytorch"]),
    ("Keras", "Data & ML", ["keras"]),
    ("scikit-learn", "Data & ML", ["scikit-learn", "sklearn"]),
    ("Pandas", "Data & ML", ["pandas"]),
    ("NumPy", "Data & ML", ["numpy"]),
    ("Spark", "Data & ML", ["apache spark"]),
    ("Hadoop", "Data & ML", ["hadoop"]),
    ("Airflow", "Data & ML", ["airflow"]),
    ("Kafka", "Data & ML", ["kafka"]),

    ("Selenium", "QA & Testing", ["selenium"]),
    ("Cypress", "QA & Testing", ["cypress"]),
    ("Playwright", "QA & Testing", ["playwright"]),
    ("PyTest", "QA & Testing", ["pytest", "py.test"]),
    ("JUnit", "QA & Testing", ["junit"]),
    ("Jest", "QA & Testing", ["jest"]),
    ("Mocha", "QA & Testing", ["mocha"]),
    ("Cucumber", "QA & Testing", ["cucumber"]),
    ("Appium", "QA & Testing", ["appium"]),
    ("Postman", "QA & Testing", ["postman"]),
    ("JMeter", "QA & Testing", ["jmeter"]),
    ("Gatling", "QA & Testing", ["gatling"]),
    ("k6", "QA & Testing", ["k6"]),

    ("Git", "Collaboration", ["git"]),
    ("GitHub", "Collaboration", ["github"]),
    ("GitLab", "Collaboration", ["gitlab"]),
    ("Bitbucket", "Collaboration", ["bitbucket"]),
    ("Jira", "Collaboration", ["jira"]),
    ("Confluence", "Collaboration", ["confluence"]),
    ("Slack", "Collaboration", ["slack"]),
    ("Docker Hub", "Collaboration", ["docker hub"]),
]

_EXCLUDE = {"c", "r", "go", "ids", "ips", "safe", "bro", "route", "switching", "rest"}
_BOUND = "[A-Za-z0-9+#.\\-]"


def _build_matcher():
    vm: dict[str, tuple[str, str]] = {}
    for display, cat, variants in CANON:
        for v in variants:
            vl = v.lower()
            if vl in _EXCLUDE or vl in vm:
                continue
            vm[vl] = (display, cat)
    ordered = sorted(vm, key=len, reverse=True)
    rx = _re.compile(
        r"(?<!" + _BOUND + r")(" + "|".join(_re.escape(v) for v in ordered) + r")(?!" + _BOUND + r")",
        _re.IGNORECASE,
    )
    return vm, rx


_VARIANT, _RX = _build_matcher()
_TAG = _re.compile(r"<[^>]+>")
_WS = _re.compile(r"\s+")


def job_text(job) -> str:
    parts = [getattr(job, "title", "") or ""]
    raw = getattr(job, "raw", None)
    if isinstance(raw, dict):
        for k in ("descriptionPlain", "description", "descriptionBody", "descriptionBodyPlain",
                  "content", "jobDescription", "additionalPlain", "additional"):
            v = raw.get(k)
            if isinstance(v, str) and v:
                parts.append(v)
    text = _TAG.sub(" ", " ".join(parts))
    text = _html.unescape(text)
    return _WS.sub(" ", text).strip().lower()


def extract_skills(text: str) -> list:
    if not text:
        return []
    found: dict[str, tuple[str, str]] = {}
    for m in _RX.finditer(text):
        info = _VARIANT.get(m.group(1).lower())
        if info:
            found[info[0]] = info
    return list(found.values())
