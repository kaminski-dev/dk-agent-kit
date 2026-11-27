# Sets dk_python to the interpreter a dk-guard hook starts with. Each hooks.json command sources this file
# and execs the hook: `. …/find-python.sh && exec "$dk_python" -I …/<hook>.py`. Sourced, not run, so the lookup
# costs no process and no second shell start, and the interpreter replaces the `sh -c` the harness started.
#
# When the first python3 on PATH is pyenv's shim, a bash script that starts `pyenv exec` and takes about
# 80 ms, dk_python is the interpreter pyenv would pick: <pyenv root>/versions/<version>/bin/python3, the
# version read as pyenv reads it, from PYENV_VERSION, else the nearest .python-version from the working
# directory up, else <pyenv root>/version.
#
# Whatever is not settled that simply stays `python3`, looked up on PATH: no pyenv, another version
# manager's shim, PYENV_DIR, several versions in PYENV_VERSION (a version file's first entry is used),
# `system`, a version prefix or one that is not installed. Every name here starts with dk_, since an
# assignment to a name the environment exports would reach the hook and the gate it runs.
#
# The hook inherits the harness's environment unchanged. `pyenv exec` put the version's bin/ first on PATH
# and exported PYENV_VERSION; nothing here does, so a gate the push hook runs finds python3 through the
# shim from its own checkout, as a gate run by hand does.
dk_python=python3

dk_first=
set -f
IFS=:
for dk_dir in $PATH; do
    if [ -x "${dk_dir:-.}/python3" ]; then
        dk_first=${dk_dir:-.}
        break
    fi
done
unset IFS
set +f

case $dk_first in
*/shims)
    dk_pyenv=${dk_first%/shims}
    dk_version=${PYENV_VERSION-}
    if [ -z "$dk_version" ] && [ -z "${PYENV_DIR-}" ]; then
        dk_file=$dk_pyenv/version
        dk_dir=$PWD
        while :; do
            if [ -f "$dk_dir/.python-version" ]; then
                dk_file=$dk_dir/.python-version
                break
            fi
            case $dk_dir in
            */*) dk_dir=${dk_dir%/*} ;;
            *) break ;;
            esac
        done
        if [ -r "$dk_file" ]; then
            read -r dk_version dk_rest < "$dk_file"
        fi
    fi
    case $dk_version in
    '' | .* | */*) ;;  # a path out of versions/ is not a version: pyenv refuses it too
    *)
        if [ -x "$dk_pyenv/versions/$dk_version/bin/python3" ]; then
            dk_python=$dk_pyenv/versions/$dk_version/bin/python3
        fi
        ;;
    esac
    ;;
esac
:
