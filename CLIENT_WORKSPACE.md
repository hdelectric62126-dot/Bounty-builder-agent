# Client workspace contract

Client code is never executed by the public dashboard or the main Railway service.
Each approved job receives its own Git branch and directory. GitHub Actions starts a
fresh hosted VM, downloads a clean language image, then runs the files inside a
second disposable Docker boundary with:

- networking disabled;
- source mounted read-only;
- an empty temporary filesystem;
- all Linux capabilities removed;
- no-new-privileges enabled;
- an unprivileged numeric user;
- no repository, Railway, Alpaca, admin, or sandbox credentials;
- CPU, memory, process, and wall-clock limits;
- fixed test commands rather than client-provided shell commands.

Test artifacts and logs are evidence for the Delivery Reviewer. Passing tests do
not publish, contact a client, merge code, or release payment. Daniel's approval is
still required.
