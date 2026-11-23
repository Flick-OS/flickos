# Sourced by the scripts that publish or read the apt repository, with ROOT
# set to their checkout. Sets REPO_DATA: the folder holding the repository's
# data (db/, public/, .gh-pages/).
#
# There is one apt repository for every Debian release, with one pool and one
# reprepro database. The checkouts of two releases (main and, after the move
# to a new release, the old one's worktree, docs/11 "After the release") must
# all use the same data: a worktree's own git-ignored repo/public/ would hold
# only its release, and repo/upload.sh's rsync --delete would then delete the
# other release from the site. So REPO_DATA is always the main worktree's
# repo/, found through git's shared folder; each checkout keeps its own
# repo/conf/ (reprepro --confdir).
#
# Falls back to ROOT's repo/ outside git, or where git can't reach the main
# worktree (a container that mounts only one worktree: there the worktree's
# repo/db, public and .gh-pages links to main's still work, docs/11). Set
# REPO_DATA beforehand to use another folder.

if [ -z "${REPO_DATA:-}" ]; then
    REPO_DATA="$ROOT/repo"
    _common="$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || _common=
    case "$_common" in
    */.git) [ -d "${_common%/.git}/repo" ] && REPO_DATA="${_common%/.git}/repo" ;;
    esac
    unset _common
fi
