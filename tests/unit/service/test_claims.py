"""``Claims`` (issue-36 R5.3, R5.8, abuse case 4): one process refuses a second harness
with the same agent id, the same namespace and task queue, or the same store file. A claim
is all or nothing, and a release frees it."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from tiny_harness.errors import HarnessConflictError
from tiny_harness.service.claims import Claim, Claims


def claim(tmp_path: Path, agent: str, queue: str, store: str = "") -> Claim:
    return Claim(
        agent_id=agent,
        namespace="default",
        task_queue=queue,
        store_path=tmp_path / (store or f"{agent}.sqlite3"),
    )


def test_distinct_agents_all_claim(tmp_path: Path) -> None:
    claims = Claims()
    for name in "abcde":
        claims.claim(claim(tmp_path, name, name))
    assert claims.held() == 5


@pytest.mark.parametrize(
    ("second", "clash"),
    [
        (("a", "q2", "other.sqlite3"), "agent id 'a'"),
        (("b", "a", "other.sqlite3"), "task queue 'a' in namespace 'default'"),
        (("b", "q2", "a.sqlite3"), "store file"),
    ],
)
def test_each_clash_names_the_holder(
    tmp_path: Path, second: tuple[str, str, str], clash: str
) -> None:
    claims = Claims()
    claims.claim(claim(tmp_path, "a", "a"))
    with pytest.raises(HarnessConflictError) as caught:
        claims.claim(claim(tmp_path, *second))
    assert clash in caught.value.message
    assert caught.value.detail["holder"] == "a"


def test_two_spellings_of_one_store_clash(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    claims = Claims()
    claims.claim(claim(tmp_path, "a", "a", "a.sqlite3"))
    with pytest.raises(HarnessConflictError):
        claims.claim(claim(tmp_path, "b", "b", "sub/../a.sqlite3"))


def test_a_refused_claim_reserves_nothing(tmp_path: Path) -> None:
    claims = Claims()
    claims.claim(claim(tmp_path, "a", "a"))
    with pytest.raises(HarnessConflictError):
        claims.claim(claim(tmp_path, "b", "a"))  # queue clashes; id and store were free
    claims.claim(claim(tmp_path, "b", "b"))  # so b's id and store are still free


def test_release_frees_the_claim(tmp_path: Path) -> None:
    claims = Claims()
    first = claim(tmp_path, "a", "a")
    claims.claim(first)
    claims.release(first)
    claims.claim(claim(tmp_path, "a", "a"))
    assert claims.held() == 1


def test_concurrent_claims_of_one_id_admit_one(tmp_path: Path) -> None:
    claims = Claims()
    won: list[str] = []
    barrier = threading.Barrier(8)

    def attempt(n: int) -> None:
        barrier.wait()
        try:
            claims.claim(claim(tmp_path, "a", f"q{n}", f"s{n}.sqlite3"))
            won.append(str(n))
        except HarnessConflictError:
            pass

    threads = [threading.Thread(target=attempt, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(won) == 1


def test_two_harnesses_cannot_share_a_public_url(tmp_path: Path) -> None:
    """Self-review round 2, finding 2."""
    claims = Claims()
    url = "http://h/agents/a"
    claims.claim(Claim("a", "default", "a", tmp_path / "a.sqlite3", public_url=url))
    with pytest.raises(HarnessConflictError) as caught:
        claims.claim(Claim("b", "default", "b", tmp_path / "b.sqlite3", public_url=url))
    assert "public URL" in caught.value.message
