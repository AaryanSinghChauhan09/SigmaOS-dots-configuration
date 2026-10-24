    # SigmaOS-dots-configuration

    Dotfiles manager (omadots-style)

    Part of the **SigmaOS** sovereign operating-system ecosystem — a multi-repository
    distribution modelled on Linux Mint and Omarchy Linux. See the parent
    [`SigmaOS`](https://github.com/AaryanSinghChauhan09/SigmaOS) repository for the
    full component index.

    ## Upstream inspirations
    - https://github.com/omacom/omadots

    ## Design principles applied
    - **Single Source of Truth**
- **Plan Before Act**
- **Defensive Programming**
- **Fail-Fast**
- **Least Astonishment**
- **KISS**
- **DRY**

    ## Usage
    Verbs: `link, sync-plan, backup, diff, profile`

    ```
    $ sigma-dots profile --profiles ./profiles
workstation  link:3 copy:1
server       link:1 copy:0
$ sigma-dots link --profiles ./profiles --profile work --home ~/. --execute
link .bashrc -> ~/.bashrc
$ sigma-dots sync-plan --profiles ./profiles --profile work --home ~/
copy .config/git/ignore  (content differs)
$ sigma-dots diff --profiles ./profiles --profile work --home ~/
match .bashrc
$ sigma-dots backup --profiles ./profiles --profile work --home ~/ --to ~/.dots-backup

    ```

    ## Build & test
    ```
    make build
    make test
    ```

    ## Licence
    GNU General Public License v3.0 (FOSS).
