# Contributing to GCP Enterprise Multi-Agent Governance Platform

Thank you for your interest in contributing to this open-source project! We welcome contributions from developers, security researchers, and AI architects.

---

## 🛠️ How to Contribute

### 1. Reporting Bugs & Issues
- Check the GitHub Issues tab to ensure your issue hasn't already been reported.
- Open a new issue with a clear title, description, and steps to reproduce. Include GCP log outputs or stack traces if available.

### 2. Submitting Pull Requests (PRs)
1. **Fork** the repository.
2. **Create a topic branch**: `git checkout -b feature/amazing-new-agent`.
3. **Make your changes** following our code style guidelines.
4. **Run the tests and the eval harness** to verify everything passes:
   ```bash
   pytest
   python evals/run_eval.py
   ```
5. **Commit your changes** with descriptive commit messages.
6. **Push to your fork** and submit a Pull Request targeting `main`.

---

## 🔌 Adding Custom Agent Plugins

When contributing a new agent microservice plugin:
1. Ensure the agent uses a dedicated **Service Account identity** pattern (`agent-<name>@...`).
2. Adhere to **Least Privilege IAM Physics**—agents should only hold permissions for the specific GCP resources they require.
3. Include unit tests verifying both happy-path execution and security containment (`403 PERMISSION_DENIED` on unauthorized endpoints).

---

## 🔒 Security Disclosures

If you discover a security vulnerability or IAM bypass issue, please **do not open a public issue**. Instead, report it privately through [GitHub's security advisory form](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability) on this repository.

---

## 📄 Licensing
By submitting a Pull Request, you agree that your contributions will be licensed under the project's [MIT License](LICENSE).
