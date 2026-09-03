"""End-to-end: staged YAML -> append-only store -> clusters -> corpus run -> stats."""

import json
from pathlib import Path

import pytest
import yaml

from newsab_corpus import (
    HAN_FOLD_VERSION,
    assign_clusters,
    compute_stats,
    containment,
    fold_han,
    shingles,
)
from newsab_corpus.cli import main
from newsab_corpus.fetch import _filename_for
from newsab_schema.artifacts import verify_manifest
from newsab_schema.ids import make_article_id
from newsab_schema.io import load_articles
from newsab_schema.models.corpus import ScopeApproval, TopicManifest
from newsab_schema.paths import TopicPaths, source_registry_path
from newsab_schema.store import (
    load_corpus_run,
    load_registry,
    load_run_articles,
    save_registry,
)

WIRE_BODY = (
    "美国国务院宣布将学生签证由身份有效期改为固定停留期限，新规定于九月十五日生效。"
    "该部门表示这一调整适用于所有新申请人。"
    "教育机构被要求在系统中更新相关记录。"
    "相关细则将在联邦公报上公布。"
    "申请人可在官方网站查询自身状态。"
)

#: WIRE_BODY as a traditional-script outlet would run it — the same sentences, but the
#: two scripts share almost no raw 5-character shingle.
TRADITIONAL_WIRE_BODY = (
    "美國國務院宣布將學生簽證由身份有效期改為固定停留期限，新規定於九月十五日生效。"
    "該部門表示這一調整適用於所有新申請人。"
    "教育機構被要求在系統中更新相關記錄。"
    "相關細則將在聯邦公報上公佈。"
    "申請人可在官方網站查詢自身狀態。"
)

ORIGINAL_BODY = (
    "多位在美中国留学生家长表示，原有的升学与租房安排被打乱。"
    "一位来自上海的家长说，孩子的实习计划需要重新考虑。"
    "留学中介机构称咨询量在过去两周明显上升。"
    "部分高校国际学生办公室已开始举办说明会。"
    "有学生表示会继续等待细则公布后再做决定。"
)


#: Bodies that share no 5-character shingle, so each stays its own reporting cluster.
#: Tests about identity and extension must not accidentally test the clusterer.
DISTINCT_BODIES = [
    "教育部门负责人在记者会上说明了新的登记流程与配套安排。"
    "地方院校反映其国际学生办公室的人手仍然不足。"
    "多家中介机构表示咨询电话在近两周持续增加。"
    "一位负责人提到相关系统的升级尚未全部完成。"
    "有关部门称后续细则将陆续对外公布。",
    "航空公司调整了往返航线的班次安排以应对客流变化。"
    "旅行社称暑期订单结构与去年同期存在明显差异。"
    "机场方面通报了值机柜台的排队等候时长。"
    "行业协会建议旅客预留更充裕的转机时间。"
    "有旅客反映改签手续办理耗时较长。",
    "研究机构发布的报告分析了近年的入学人数走向。"
    "报告作者指出统计口径与往年存在差别。"
    "受访学者认为单一指标不足以说明整体状况。"
    "该机构表示将在下季度更新其数据面板。"
    "报告同时列出了若干尚未解决的方法学问题。",
]


def registration(country="CN", category="other", beat_scope="vertical"):
    """The block a collector fills in the first article it stages from a new outlet."""
    return {
        "source_country": country,
        "source_url": "https://newoutlet.example.com/",
        "source_name_en": "New Outlet Daily",
        "source_name_zh": "新媒体日报",
        "source_category": category,
        "source_beat_scope": beat_scope,
        "source_notes_en": "A metals trade publisher funded by its subscribers.",
        "source_notes_zh": "以订阅收入为主的金属行业媒体。",
    }


def source(sid, country, lang, category="serious"):
    return {
        "id": sid,
        "name": {"values": {"en": f"The {sid} Herald", "zh-CN": f"{sid} 报"}},
        "url": "https://example.com",
        "lang": lang,
        "country": country,
        "category": category,
        "notes": {"values": {"en": "A test fixture outlet.", "zh-CN": "测试用媒体。"}},
    }


@pytest.fixture
def topic(tmp_path):
    """A throwaway repo: ``tmp_path/topics/<id>`` plus the sibling ``tmp_path/sources/``.

    The registry is a sibling of ``topics/`` rather than a child of the topic because it
    is cross-topic (R-3), so a fixture has to build both halves.
    """
    root = tmp_path / "topics"
    paths = TopicPaths.for_topic(root, "aabb-river-light-2026").ensure()
    (paths.corpus_dir / "staging").mkdir(parents=True, exist_ok=True)

    registry_path = source_registry_path(root)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        yaml.safe_dump(
            {
                "registry_version": "test-0.1.0",
                "updated_at": "2026-08-17T18:00:00Z",
                "sources": [
                    source("cn_agency", "CN", "zh-CN", "other"),
                    source("cn_paper_a", "CN", "zh-CN"),
                    source("cn_paper_b", "CN", "zh-CN"),
                    source("us_paper", "US", "en"),
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    manifest = TopicManifest.model_validate(
            {
                "topic_id": "aabb-river-light-2026",
                "status": "active",
                "title": {"values": {"en": "test topic"}},
                "groups": [
                    {
                        "group_id": "cn",
                        "prefix": "CN",
                        "label": {"values": {"en": "cn"}},
                        "short_label": {"values": {"en": "CN side"}},
                        "definition": {"values": {"en": "Chinese test coverage"}},
                    },
                    {
                        "group_id": "us",
                        "prefix": "US",
                        "label": {"values": {"en": "us"}},
                        "short_label": {"values": {"en": "US side"}},
                        "definition": {"values": {"en": "US test coverage"}},
                    },
                ],
                "period": {"start": "2026-05-01", "end": "2026-12-31"},
                "include": ["the test policy round"],
                "provenance": {
                    "skill_version": "S0-0.1.0",
                    "model_id": None,
                    "run_id": "s0-202608171800-00000000",
                    "timestamp": "2026-08-17T18:00:00Z",
                },
            }
    )
    manifest = manifest.model_copy(update={"scope_approval": ScopeApproval(
        approved_by="test founder",
        approved_at="2026-08-17T18:00:00Z",
        scope_hash=manifest.scope_hash(),
    )})
    paths.topic_manifest.write_text(
        yaml.safe_dump(manifest.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return root, paths


def stage(paths: TopicPaths, name: str, **fields):
    payload = {
        "group_id": "cn",
        "source_id": "cn_agency",
        "url": f"https://example.com/{Path(name).stem}",
        "title": "标题",
        "publish_date": "2026-07-01",
        "lang": "zh-CN",
        "access_level": "full",
        "origin": {"type": "original"},
        "body": ORIGINAL_BODY,
    }
    payload.update(fields)
    (paths.corpus_dir / "staging" / name).write_text(
        yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8"
    )
    return payload["url"]


def test_build_assigns_content_addressed_ids_and_clusters(topic, capsys):
    root, paths = topic
    wire = stage(paths, "cn-0001.yaml", source_id="cn_agency", title="通稿原文", body=WIRE_BODY)
    reprint = stage(
        paths,
        "cn-0002.yaml",
        source_id="cn_paper_a",
        title="转载：本报讯",
        body=WIRE_BODY,
        origin={"type": "domestic_wire", "wire_source": "cn_agency", "headline_changed": True},
    )
    local = stage(paths, "cn-0003.yaml", source_id="cn_paper_b", title="家长的担忧", body=ORIGINAL_BODY)

    assert main(["build", str(root), "aabb-river-light-2026"]) == 0

    # The ID is derived from the article's own URL, not from its position in the build.
    ids = {name: make_article_id("CN", url) for name, url in
           (("wire", wire), ("reprint", reprint), ("local", local))}
    assert sorted(a.article_id for a in load_articles(paths.articles_dir)) == sorted(ids.values())

    run = load_corpus_run(paths)
    clusters = run.cluster_assignment
    assert clusters[ids["wire"]] == clusters[ids["reprint"]], "identical wire copy is one cluster"
    assert clusters[ids["local"]] != clusters[ids["wire"]], "independent reporting is its own"

    # 3 publication instances, 2 independent clusters — the D7 headline number.
    cn = run.build_report["stats"]["groups"]["cn"]
    assert (cn["publication_instances"], cn["independent_clusters"]) == (3, 2)
    assert cn["homogeneity"] == pytest.approx(1 / 3)

    manifest = [json.loads(line) for line in paths.manifest.read_text(encoding="utf-8").splitlines()]
    assert manifest[-1]["skill_id"] == "newsab-corpus/build"
    assert manifest[-1]["run_id"] == paths.active_run_id("corpus")
    assert manifest[-1]["stage"] == "corpus"
    assert manifest[-1]["output_set_hash"] == run.set_hash
    assert verify_manifest(paths) == []


def test_an_unpinned_threshold_override_warns_loudly(topic, capsys):
    """--threshold without a manifest pin is a denominator only this invocation has."""
    root, paths = topic
    stage(paths, "cn-0001.yaml")

    assert main(["build", str(root), "aabb-river-light-2026", "--threshold", "0.94"]) == 0
    run = load_corpus_run(paths)
    assert run.cluster_threshold == 0.94
    unpinned = [w for w in run.warnings if "not pinned in topic_manifest" in w]
    assert unpinned, run.warnings
    assert "0.94" in unpinned[0] and "rebuild" in unpinned[0]

    # Pinned in the manifest, the same value draws no warning.  The field sits outside
    # the signed surface, so pinning it is the collecting
    # agent's own move and the recorded approval hash stays valid.
    pinned = TopicManifest.model_validate(
        yaml.safe_load(paths.topic_manifest.read_text(encoding="utf-8"))
    ).model_copy(update={"cluster_threshold": 0.94})
    paths.topic_manifest.write_text(
        yaml.safe_dump(pinned.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    assert main(["build", str(root), "aabb-river-light-2026", "--threshold", "0.94"]) == 0
    run = load_corpus_run(paths)
    assert not [w for w in run.warnings if "not pinned in topic_manifest" in w]


def test_build_blocks_without_hash_bound_human_scope_approval(topic, capsys):
    root, paths = topic
    raw = yaml.safe_load(paths.topic_manifest.read_text(encoding="utf-8"))
    raw["scope_approval"] = None
    paths.topic_manifest.write_text(
        yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    stage(paths, "cn-0001.yaml")

    assert main(["build", str(root), "aabb-river-light-2026"]) == 1
    assert "human touchpoint #1" in capsys.readouterr().err
    assert paths.active_run_id("corpus") is None


def test_build_blocks_when_scope_changed_after_approval(topic, capsys):
    root, paths = topic
    raw = yaml.safe_load(paths.topic_manifest.read_text(encoding="utf-8"))
    raw["include"].append("an unapproved scope expansion")
    paths.topic_manifest.write_text(
        yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    stage(paths, "cn-0001.yaml")

    assert main(["build", str(root), "aabb-river-light-2026"]) == 1
    assert "scope changed after human approval" in capsys.readouterr().err
    assert paths.active_run_id("corpus") is None


def test_explicit_group_membership_is_not_rederived_from_country_or_language(topic):
    root, paths = topic
    stage(
        paths,
        "cn-0001.yaml",
        group_id="cn",
        source_id="us_paper",
        lang="en",
        title="A semantically assigned story",
        body="This article is assigned by the collector against the group definition.",
    )

    assert main(["build", str(root), "aabb-river-light-2026"]) == 0
    article = load_run_articles(paths)[0]
    assert article.article_id.startswith("CN_")
    assert article.lang == "en"


def test_article_id_does_not_move_when_a_neighbour_is_removed(topic):
    """The defect content addressing exists to remove (R-1).

    Under build-order serials, dropping an article shifted every later ID, and with them
    every ``{article_id}:P{n}:S{n}`` anchor S4 had already written.
    """
    root, paths = topic
    stage(paths, "cn-0001.yaml", body=DISTINCT_BODIES[0])
    stage(paths, "cn-0002.yaml", source_id="cn_paper_a", body=DISTINCT_BODIES[1])
    stage(paths, "cn-0003.yaml", source_id="cn_paper_b", body=DISTINCT_BODIES[2])
    assert main(["build", str(root), "aabb-river-light-2026"]) == 0
    before = {a.article_id: a.sentence_ids() for a in load_run_articles(paths)}

    (paths.corpus_dir / "staging" / "cn-0002.yaml").unlink()
    third = make_article_id("CN", "https://example.com/cn-0003")
    assert main(["withdraw", str(root), "aabb-river-light-2026",
                 make_article_id("CN", "https://example.com/cn-0002"),
                 "--reason", "test withdrawal"]) == 0
    assert main(["build", str(root), "aabb-river-light-2026"]) == 0

    after = {a.article_id: a.sentence_ids() for a in load_run_articles(paths)}
    assert third in after
    assert after[third] == before[third], "a removal must not move another article's anchors"


def test_sentence_ids_are_reproducible_across_builds(topic):
    root, paths = topic
    url = stage(paths, "cn-0001.yaml", body=ORIGINAL_BODY)
    assert main(["build", str(root), "aabb-river-light-2026"]) == 0
    first = load_run_articles(paths)[0].sentence_ids()
    assert main(["build", str(root), "aabb-river-light-2026"]) == 0
    assert load_run_articles(paths)[0].sentence_ids() == first
    assert first[0] == f"{make_article_id('CN', url)}:P00:S01"


def test_extending_an_annotated_corpus_leaves_existing_records_untouched(topic, capsys):
    """R-2's whole point: adding an article costs one file and one run, not a re-annotation.

    Before the refactor this build refused outright once observations existed, which is
    what turned "we found one more in-period article" into a decision for the user.
    """
    root, paths = topic
    first_url = stage(paths, "cn-0001.yaml", body=DISTINCT_BODIES[0])
    assert main(["build", str(root), "aabb-river-light-2026"]) == 0
    first_id = make_article_id("CN", first_url)
    before_bytes = paths.article_file(first_id).read_bytes()
    first_run = load_corpus_run(paths)

    paths.observations.parent.mkdir(parents=True, exist_ok=True)
    paths.observations.write_text("", encoding="utf-8")
    stage(paths, "cn-0002.yaml", source_id="cn_paper_a", body=DISTINCT_BODIES[1])

    assert main(["build", str(root), "aabb-river-light-2026"]) == 0
    assert paths.article_file(first_id).read_bytes() == before_bytes
    second_run = load_corpus_run(paths)
    assert second_run.run_id != first_run.run_id
    assert set(second_run.article_ids) > set(first_run.article_ids)
    # The old run still describes the world it saw, and can still be restored from the store.
    assert load_run_articles(paths, first_run.run_id) != []
    assert "1 new article(s) need annotating" in capsys.readouterr().out


def test_recollected_content_is_superseded_not_overwritten(topic):
    root, paths = topic
    url = stage(paths, "cn-0001.yaml", body=ORIGINAL_BODY)
    assert main(["build", str(root), "aabb-river-light-2026"]) == 0
    old_run = load_corpus_run(paths)

    stage(paths, "cn-0001.yaml", body=ORIGINAL_BODY + "后来补充的一段说明性文字。")
    assert main(["build", str(root), "aabb-river-light-2026"]) == 0

    article_id = make_article_id("CN", url)
    assert load_run_articles(paths, old_run.run_id)[0].article_id == article_id
    assert list(paths.superseded_articles_dir.glob(f"{article_id}.*.json"))
    assert load_corpus_run(paths).content_hashes != old_run.content_hashes
    assert verify_manifest(paths) == []


def test_withdrawal_records_a_reason_instead_of_deleting(topic):
    root, paths = topic
    url = stage(paths, "cn-0001.yaml", body=DISTINCT_BODIES[0])
    stage(paths, "cn-0002.yaml", source_id="cn_paper_a", body=DISTINCT_BODIES[1])
    assert main(["build", str(root), "aabb-river-light-2026"]) == 0

    article_id = make_article_id("CN", url)
    assert main(["withdraw", str(root), "aabb-river-light-2026", article_id,
                 "--reason", "carrier page; the publisher is another outlet"]) == 0
    assert main(["build", str(root), "aabb-river-light-2026"]) == 0

    run = load_corpus_run(paths)
    assert article_id not in run.article_ids
    assert [w.reason for w in run.withdrawn] == ["carrier page; the publisher is another outlet"]
    assert paths.article_file(article_id).exists(), "withdrawal keeps the record, so old runs restore"


def test_headline_block_holds_title_and_subtitle(topic):
    root, paths = topic
    url = stage(paths, "cn-0001.yaml", title="主标题", subtitle="副标题", body=ORIGINAL_BODY)
    main(["build", str(root), "aabb-river-light-2026"])
    article_id = make_article_id("CN", url)
    article = load_run_articles(paths)[0]
    assert article.sentence_text(f"{article_id}:P00:S01") == "主标题"
    assert article.sentence_text(f"{article_id}:P00:S02") == "副标题"


def test_two_articles_declared_original_in_one_cluster_blocks_the_build(topic, capsys):
    """The cluster count is the denominator for every prevalence claim, so a contradiction
    between the declared origin and the text similarity has to stop the run (D7)."""
    root, paths = topic
    stage(paths, "cn-0001.yaml", source_id="cn_agency", body=WIRE_BODY)
    stage(paths, "cn-0002.yaml", source_id="cn_paper_a", body=WIRE_BODY)
    assert main(["build", str(root), "aabb-river-light-2026"]) == 1
    assert "origin=original" in capsys.readouterr().out
    assert paths.active_run_id("corpus") is None, "a blocked build must not become active"


# --- relevance, beat scope, and classifying a new outlet ----------------------------------


def test_a_peripheral_cluster_is_reported_but_no_longer_leaves_the_denominator(topic, capsys):
    """The label survives on the record; it excludes nothing.

    The build used to call the core count "the denominator" and say peripheral clusters
    were "excluded from every prevalence denominator".  Both stopped being true when the
    lever was retired and analyze began counting every cluster — and the stale wording
    went on telling operators otherwise.
    """
    root, paths = topic
    stage(paths, "cn-0001.yaml", body=ORIGINAL_BODY)
    stage(
        paths,
        "cn-0002.yaml",
        source_id="cn_paper_a",
        title="每日行情综述",
        body=WIRE_BODY,
        topic_relevance="peripheral",
    )
    assert main(["build", str(root), "aabb-river-light-2026"]) == 0
    out = capsys.readouterr().out
    assert "labelled peripheral" in out
    # The printout must not claim the label moves a denominator any more.
    assert "excluded from every prevalence denominator" not in out
    assert "core, the denominator" not in out
    assert "2 clusters, the denominator" in out

    run = load_corpus_run(paths)
    assert len(run.core_clusters) == 1
    assert len(run.peripheral_clusters) == 1
    # …and the article itself is still there, still quotable.
    assert len(run.articles) == 2
    assert run.build_report["stats"]["groups"]["cn"]["peripheral_clusters"] == 1


def test_one_core_member_keeps_the_whole_cluster_in_the_denominator(topic):
    """A real report seen through three market wraps is still a real report."""
    root, paths = topic
    stage(paths, "cn-0001.yaml", body=WIRE_BODY, topic_relevance="core")
    stage(
        paths,
        "cn-0002.yaml",
        source_id="cn_paper_a",
        title="转载",
        body=WIRE_BODY,
        topic_relevance="peripheral",
        origin={"type": "domestic_wire", "wire_source": "cn_agency"},
    )
    assert main(["build", str(root), "aabb-river-light-2026"]) == 0
    run = load_corpus_run(paths)
    assert len(run.core_clusters) == 1 and run.peripheral_clusters == []


def test_an_unlabelled_corpus_counts_exactly_as_it_did_before(topic):
    """Relevance labelling must be inert on every run built before it: `core` is the default."""
    root, paths = topic
    stage(paths, "cn-0001.yaml", body=ORIGINAL_BODY)
    stage(paths, "cn-0002.yaml", source_id="cn_paper_a", title="独立报道", body=WIRE_BODY)
    assert main(["build", str(root), "aabb-river-light-2026"]) == 0
    run = load_corpus_run(paths)
    assert run.peripheral_clusters == []
    assert len(run.core_clusters) == len(set(run.cluster_assignment.values()))


def test_an_unknown_relevance_label_is_refused(topic, capsys):
    root, paths = topic
    stage(paths, "cn-0001.yaml", body=ORIGINAL_BODY, topic_relevance="mostly")
    assert main(["build", str(root), "aabb-river-light-2026"]) == 1
    assert "topic_relevance" in capsys.readouterr().err


def test_a_new_outlet_is_described_by_the_run_that_met_it(topic, capsys):
    """The registry has no human tier: the entry a run writes is the finished entry."""
    root, paths = topic
    stage(paths, "cn-0001.yaml", source_id="new_trade_cn", body=ORIGINAL_BODY, **registration())
    assert main(["build", str(root), "aabb-river-light-2026"]) == 0
    assert "registered in" in capsys.readouterr().out

    registry = load_registry(source_registry_path(root))
    added = registry.by_id("new_trade_cn")
    assert added.beat_scope == "vertical"
    assert added.name.values["zh-CN"] == "新媒体日报", "a reader sees a masthead, not a slug"
    assert added.url == "https://newoutlet.example.com/", "the front page, not the article"
    assert "subscribers" in added.notes.values["en"]
    assert "订阅" in added.notes.values["zh-CN"]


def test_a_half_filled_registration_block_is_refused(topic, capsys):
    """Half a registration used to be completed with placeholders nobody revisited."""
    root, paths = topic
    block = registration()
    del block["source_notes_zh"]
    stage(paths, "cn-0001.yaml", source_id="new_outlet_cn", body=ORIGINAL_BODY, **block)
    assert main(["build", str(root), "aabb-river-light-2026"]) == 1
    assert "source_notes_zh" in capsys.readouterr().err


def test_an_unregistered_outlet_with_no_block_stops_the_build(topic, capsys):
    """Nobody downstream can describe this outlet, so the run that met it has to."""
    root, paths = topic
    stage(paths, "cn-0001.yaml", source_id="mystery_cn", body=ORIGINAL_BODY)
    assert main(["build", str(root), "aabb-river-light-2026"]) == 1
    assert "registration block" in capsys.readouterr().err


def test_the_two_sides_being_different_kinds_of_newsroom_is_reported(topic, capsys):
    """Same cluster count, different composition — the bias `category` alone cannot see."""
    root, paths = topic
    registry_path = source_registry_path(root)
    registry = load_registry(registry_path)
    trade = [
        s.model_copy(update={"beat_scope": "vertical"})
        if s.id.startswith("cn_")
        else s.model_copy(update={"beat_scope": "general"})
        for s in registry.sources
    ]
    save_registry(registry_path, registry.model_copy(update={"sources": trade}))

    zh = [
        "上海一家留学中介说，本周来咨询改签方案的家庭比上周多了一倍。",
        "广州的一所高校国际处表示，正在为九月入学的学生准备补充材料清单。",
        "北京多位家长谈到，孩子原定的暑期实习安排现在要重新排。",
    ]
    en = [
        "A Boston immigration lawyer said her office fielded calls from graduate students all week.",
        "Campus officials in Texas are rewriting orientation packets for the coming term.",
        "Two Midwestern universities have scheduled town halls for international students.",
    ]
    for i in range(3):
        stage(
            paths,
            f"cn-000{i + 1}.yaml",
            source_id="cn_paper_a" if i else "cn_agency",
            title=f"中文报道{i}",
            url=f"https://example.com/cn-{i}",
            body=zh[i],
        )
        stage(
            paths,
            f"us-000{i + 1}.yaml",
            group_id="us",
            source_id="us_paper_a",
            **registration(country="US", category="serious", beat_scope="general"),
            title=f"US report {i}",
            lang="en",
            url=f"https://example.com/us-{i}",
            body=en[i],
        )
    assert main(["build", str(root), "aabb-river-light-2026"]) == 0
    out = capsys.readouterr().out
    assert "beat composition differs across the sides" in out
    assert "cn 100%" in out and "us 0%" in out

    # The cell is `category × beat_scope`: the cn side is one `other` outlet and one
    # `serious` one, both vertical — exactly the split `category` alone cannot express.
    stats = load_corpus_run(paths).build_report["stats"]
    cn_beat = stats["groups"]["cn"]["by_beat"]
    assert sorted(cn_beat) == ["other/vertical", "serious/vertical"]
    assert sum(cell["clusters"] for cell in cn_beat.values()) == 3
    assert stats["groups"]["us"]["by_beat"]["serious/general"]["clusters"] == 3
    assert stats["beat_imbalance"] == [
        {"group_id": "cn", "vertical_share": 1.0},
        {"group_id": "us", "vertical_share": 0.0},
    ]


def test_observed_language_composition_and_dominance_hint_are_reported(topic, capsys):
    """A language-axis hint describes receipts; it does not create a language quota."""
    root, paths = topic
    bodies = [
        "Harbour officials published a new timetable for vessel inspections.",
        "University advisers opened an evening desk for student questions.",
        "Regional airlines changed their booking policy before the holiday period.",
        "Court clerks released the written order after the afternoon hearing.",
    ]
    for index, body in enumerate(bodies, start=1):
        stage(
            paths,
            f"cn-en-{index:04d}.yaml",
            title=f"English report {index}",
            url=f"https://example.com/cn-en-{index}",
            lang="en",
            body=body,
        )
    stage(
        paths,
        "cn-hi-0001.yaml",
        title="Hindi report",
        url="https://example.com/cn-hi-1",
        lang="hi",
        body="स्थानीय अधिकारियों ने नई प्रक्रिया की जानकारी दी।",
    )

    assert main(["build", str(root), "aabb-river-light-2026"]) == 0
    out = capsys.readouterr().out
    assert "languages: en 4 instance(s) / 4 cluster(s), hi 1 instance(s) / 1 cluster(s)" in out
    assert "thin-language: cn/hi is 1/5 publication instance(s) (20%)" in out
    assert "not a quota or gate" in out

    stats = load_corpus_run(paths).build_report["stats"]
    assert stats["groups"]["cn"]["by_language"] == {
        "en": {"instances": 4, "clusters": 4},
        "hi": {"instances": 1, "clusters": 1},
    }
    assert stats["thin_languages"] == [
        {
            "group_id": "cn",
            "lang": "hi",
            "instances": 1,
            "total_instances": 5,
            "instance_share": 0.2,
        }
    ]


def test_a_single_observed_language_does_not_invent_a_thin_language(topic, capsys):
    root, paths = topic
    for index, body in enumerate(DISTINCT_BODIES, start=1):
        stage(paths, f"cn-{index:04d}.yaml", body=body)

    assert main(["build", str(root), "aabb-river-light-2026"]) == 0
    out = capsys.readouterr().out
    assert "thin-language:" not in out
    assert load_corpus_run(paths).build_report["stats"]["thin_languages"] == []


def test_staged_body_sentences_are_reported_against_raw_visible_text(topic, capsys):
    root, paths = topic
    matching_url = stage(
        paths,
        "cn-0001.yaml",
        body="The first line stays visible.\n\nThe second line stays visible.",
        lang="en",
    )
    glued_url = stage(
        paths,
        "cn-0002.yaml",
        source_id="cn_paper_a",
        body="Section heading Next sentence is here.",
        lang="en",
    )
    raw = paths.corpus_dir / "raw"
    raw.mkdir()
    (raw / _filename_for(matching_url)).write_text(
        "<html><body><p>The first line stays visible.</p>"
        "<p>The second line stays visible.</p></body></html>",
        encoding="utf-8",
    )
    # The staged extractor glued an h2 to a later sentence across an intervening block;
    # no reader can Ctrl-F the resulting staged sentence in this snapshot.
    (raw / _filename_for(glued_url)).write_text(
        "<html><body><h2>Section heading</h2><aside>intervening block</aside>"
        "<p>Next sentence is here.</p></body></html>",
        encoding="utf-8",
    )

    assert main(["build", str(root), "aabb-river-light-2026"]) == 0
    out = capsys.readouterr().out
    assert "3 body sentence(s) checked, 1 not found" in out
    assert "report-only, not a build gate" in out
    assert paths.active_run_id("corpus") is not None

    report = load_corpus_run(paths).build_report["staged_snapshot_verbatim"]
    assert report["report_only"] is True
    assert report["checked_articles"] == 2
    assert report["checked_sentences"] == 3
    assert report["missing_snapshots"] == []
    assert len(report["sentences_not_found"]) == 1
    miss = report["sentences_not_found"][0]
    assert miss["text"] == "Section heading Next sentence is here."
    assert miss["sentence_id"].endswith(":P01:S01")


def test_missing_raw_snapshot_is_reported_without_gating_build(topic, capsys):
    root, paths = topic
    stage(paths, "cn-0001.yaml", body=ORIGINAL_BODY)

    assert main(["build", str(root), "aabb-river-light-2026"]) == 0
    out = capsys.readouterr().out
    assert "0/1 staged article snapshot(s)" in out
    assert "1 snapshot(s) missing (report-only)" in out
    report = load_corpus_run(paths).build_report["staged_snapshot_verbatim"]
    assert report["checked_sentences"] == 0
    assert report["missing_snapshots"][0]["unchecked_sentences"] > 0
    assert paths.active_run_id("corpus") is not None


# --- press releases are their own origin -------------------------------------------------


def test_a_press_release_must_name_its_issuer(topic, capsys):
    """Unattributed, a rewritten statement is indistinguishable from wire copy."""
    root, paths = topic
    stage(paths, "cn-0001.yaml", origin={"type": "press_release"}, body=ORIGINAL_BODY)
    assert main(["build", str(root), "aabb-river-light-2026"]) == 1
    assert "requires wire_source" in capsys.readouterr().err


def test_a_lone_press_release_rewrite_is_not_flagged_as_a_missing_original(topic, capsys):
    """The statement itself is never an article in the corpus, so it has no sibling to
    match.  Warning here would train the collector to ignore the warning that matters."""
    root, paths = topic
    stage(paths, "cn-0001.yaml", body=ORIGINAL_BODY)
    stage(
        paths,
        "cn-0002.yaml",
        source_id="cn_paper_a",
        title="协会公告",
        body=WIRE_BODY,
        origin={"type": "press_release", "wire_source": "中国有色金属工业协会"},
    )
    assert main(["build", str(root), "aabb-river-light-2026"]) == 0
    assert "matched no other article" not in capsys.readouterr().out

    # …and it still does not count as a newsroom having reported (D7).
    by_id = {a.article_id: a for a in load_run_articles(paths)}
    press = next(a for a in by_id.values() if a.origin.type == "press_release")
    assert not press.is_independent
    assert press.origin.wire_source == "中国有色金属工业协会"


def test_a_lone_wire_rewrite_is_still_flagged(topic, capsys):
    """The exemption is for press releases only — the wire check keeps its teeth."""
    root, paths = topic
    stage(paths, "cn-0001.yaml", body=ORIGINAL_BODY)
    stage(
        paths,
        "cn-0002.yaml",
        source_id="cn_paper_a",
        title="转载",
        body=WIRE_BODY,
        origin={"type": "domestic_wire", "wire_source": "cn_agency"},
    )
    assert main(["build", str(root), "aabb-river-light-2026"]) == 0
    assert "matched no other article" in capsys.readouterr().out


def test_index_carries_no_body_text(topic):
    root, paths = topic
    stage(paths, "cn-0001.yaml", body=ORIGINAL_BODY)
    main(["build", str(root), "aabb-river-light-2026"])
    raw = paths.corpus_index.read_text(encoding="utf-8")
    assert "多位在美中国留学生家长" not in raw, "index must never carry article body text (D14)"
    row = json.loads(raw.splitlines()[0])
    assert row["reporting_cluster_id"].startswith("RC-CN-")
    assert row["category"] == "other"


def test_unknown_source_is_registered_rather_than_blocking_the_build(topic, capsys):
    """R-3: an open source frame (D19) means meeting a new outlet is routine, not a gate."""
    root, paths = topic
    stage(
        paths, "cn-0001.yaml", source_id="never_registered", body=ORIGINAL_BODY, **registration()
    )
    assert main(["build", str(root), "aabb-river-light-2026"]) == 0

    registry = load_registry(source_registry_path(root))
    added = registry.by_id("never_registered")
    assert added.category.value == "other"
    assert added.country == "CN", "the source country comes from explicit staging metadata"
    assert "registered in" in capsys.readouterr().out


def test_silence_and_thin_categories_are_reported_not_hidden(topic, capsys):
    root, paths = topic
    stage(paths, "cn-0001.yaml", body=ORIGINAL_BODY)
    main(["build", str(root), "aabb-river-light-2026"])
    out = capsys.readouterr().out
    assert "silence: group us" in out
    assert "thin: cn/other" in out


def test_a_traditional_script_reprint_joins_the_simplified_cluster(topic):
    """The same reporting in the other Han script must not inflate D7."""
    root, paths = topic
    original = stage(paths, "cn-0001.yaml", source_id="cn_agency", body=WIRE_BODY)
    reprint = stage(
        paths,
        "cn-0002.yaml",
        source_id="cn_paper_a",
        lang="zh-TW",
        title="轉載：本報訊",
        body=TRADITIONAL_WIRE_BODY,
        origin={"type": "domestic_wire", "wire_source": "cn_agency", "headline_changed": True},
    )

    assert main(["build", str(root), "aabb-river-light-2026"]) == 0

    run = load_corpus_run(paths)
    clusters = run.cluster_assignment
    assert clusters[make_article_id("CN", original)] == clusters[make_article_id("CN", reprint)]
    assert run.cluster_han_fold == HAN_FOLD_VERSION


def test_han_fold_bridges_scripts_and_quote_conventions():
    # The folded reprint is character-identical to the simplified original, so the
    # shingle fingerprints coincide exactly — this is what lifts the measured
    # containment of 0.052 to 1.0.
    assert fold_han(TRADITIONAL_WIRE_BODY) == WIRE_BODY
    assert shingles(TRADITIONAL_WIRE_BODY) == shingles(WIRE_BODY)
    # Corner brackets (traditional quoting) fold onto simplified curly quotes.
    assert fold_han("記者在「現場」看到『告示』") == "记者在“现场”看到‘告示’"


def test_containment_beats_jaccard_for_embedded_wire_copy():
    """A local paper that runs the wire story plus three local paragraphs."""
    wire = shingles(WIRE_BODY)
    local = shingles(WIRE_BODY + ORIGINAL_BODY)
    assert containment(wire, local) > 0.95
    from newsab_corpus import jaccard

    assert jaccard(wire, local) < containment(wire, local)


def test_short_articles_stay_singletons():
    from newsab_schema.models.corpus import Article

    def tiny(article_id, cluster):
        return Article.model_validate(
            {
                "article_id": article_id,
                "topic_id": "aabb-river-light-2026",
                "source_id": "cn_agency",
                "url": "https://example.com",
                "title": "短",
                "publish_date": "2026-07-01",
                "lang": "zh-CN",
                "structured_text": [
                    {"index": 0, "sentences": [{"index": 1, "text": "短"}]},
                    {"index": 1, "sentences": [{"index": 1, "text": "很短。"}]},
                ],
                "fetch_timestamp": "2026-08-17T18:00:00Z",
                "access_level": "partial",
                "origin": {"type": "original"},
                "reporting_cluster_id": cluster,
                "splitter_version": "split-0.1.0",
                "provenance": {
                    "skill_version": "S2stage-0.1.0",
                    "model_id": None,
                    "run_id": "s2s-202608171800-00000000",
                    "timestamp": "2026-08-17T18:00:00Z",
                },
            }
        )

    assignment = assign_clusters(
        [tiny("CN_aaaaaaaa", "RC-CN-aaaaaaaa"), tiny("CN_bbbbbbbb", "RC-CN-bbbbbbbb")]
    )
    assert len(assignment.members) == 2
    assert any("too short to judge" in w for w in assignment.warnings)


def test_a_short_fragment_cannot_bridge_distinct_long_reports():
    """A title/standfirst may match both stories but cannot join their components."""
    from newsab_schema.models.corpus import Article

    common = (
        "The Indus Waters Treaty remains under discussion between India and Pakistan. "
        "Officials on both sides referred to the shared river system. "
    )
    left_body = common + (
        "The first report follows court filings, procedural orders, jurisdictional "
        "arguments, and the timetable for written submissions in the arbitration. "
        "Counsel described how the panel would receive evidence, hear objections, and "
        "publish a reasoned decision after the parties completed their pleadings. "
        "Diplomats separately discussed recognition, enforcement, and the next hearing."
    )
    right_body = common + (
        "The second report examines reservoir capacity, irrigation schedules, crop "
        "planning, canal maintenance, and seasonal forecasts for downstream farmers. "
        "Engineers described gauges, spillways, snowmelt models, and telemetry stations "
        "used to predict releases throughout the planting season. Provincial officials "
        "separately discussed drought preparation and repairs to distributary channels."
    )

    def article(article_id, body, origin="original"):
        origin_record = {"type": origin}
        if origin != "original":
            origin_record["wire_source"] = "Shared dispatch"
        return Article.model_validate(
            {
                "article_id": article_id,
                "topic_id": "aabb-canal-gate-2026",
                "source_id": "paper_in",
                "url": f"https://example.com/{article_id}",
                "title": "Treaty update",
                "publish_date": "2026-07-01",
                "lang": "en",
                "structured_text": [
                    {"index": 0, "sentences": [{"index": 1, "text": "Treaty update"}]},
                    {"index": 1, "sentences": [{"index": 1, "text": body}]},
                ],
                "fetch_timestamp": "2026-08-17T18:00:00Z",
                "access_level": "partial" if origin != "original" else "full",
                "origin": origin_record,
                "reporting_cluster_id": f"RC-{article_id.replace('_', '-')}",
                "splitter_version": "split-0.9.0",
                "provenance": {
                    "skill_version": "S2stage-0.1.1",
                    "model_id": None,
                    "run_id": "s2s-202608171800-00000000",
                    "timestamp": "2026-08-17T18:00:00Z",
                },
            }
        )

    left = article("IN_aaaaaaaa", left_body)
    right = article("IN_bbbbbbbb", right_body)
    bridge = article("IN_cccccccc", common, "syndication")
    bridge_fp = shingles(common)
    assert 20 <= len(bridge_fp) <= 256
    assert len(shingles(left_body)) > 256
    assert len(shingles(right_body)) > 256
    assert containment(bridge_fp, shingles(left_body)) >= 0.6
    assert containment(bridge_fp, shingles(right_body)) >= 0.6
    assert containment(shingles(left_body), shingles(right_body)) < 0.6

    assignment = assign_clusters([left, right, bridge])
    reversed_assignment = assign_clusters([bridge, right, left])
    assert assignment.cluster_ids[left.article_id] != assignment.cluster_ids[right.article_id]
    assert assignment.cluster_count == 2
    assert assignment.cluster_ids == reversed_assignment.cluster_ids
    assert any("short-edge bridge guard" in warning for warning in assignment.warnings)

    # The guard limits degree; it does not turn short records into forced singletons.
    # Two genuinely identical title/lead records still retain their strongest edge.
    bridge_copy = bridge.model_copy(
        update={
            "article_id": "IN_dddddddd",
            "url": "https://example.com/IN_dddddddd",
            "reporting_cluster_id": "RC-IN-dddddddd",
        }
    )
    short_pair = assign_clusters([bridge, bridge_copy])
    assert short_pair.cluster_count == 1



def test_a_mechanism_only_change_is_revised_not_superseded(topic, capsys):
    """A record can change without a single sentence moving, and the two must not look alike.

    The build's "which articles need re-annotating" line is the only statement the pipeline
    makes about what a rebuild costs downstream.  Driving it off the content hash made a
    ``splitter_version`` bump report 100% of a corpus as stale — on the visa topic, 63 of 63
    articles whose sentence sets were byte-identical — which turns every incremental rebuild
    into a full re-annotation and defeats the append-only store.
    """
    from newsab_schema.models.corpus import article_sentence_hash
    from newsab_schema.store import read_article

    root, paths = topic
    url = stage(paths, "cn-0001.yaml", body=ORIGINAL_BODY)
    assert main(["build", str(root), "aabb-river-light-2026"]) == 0
    article_id = make_article_id("CN", url)
    before = read_article(paths.article_file(article_id))

    paths.answers.parent.mkdir(parents=True, exist_ok=True)
    paths.answers.write_text("", encoding="utf-8")
    # Same bytes of body, different record: the collector corrected the origin label.
    stage(
        paths,
        "cn-0001.yaml",
        body=ORIGINAL_BODY,
        origin={"type": "press_release", "wire_source": "中国有色金属工业协会"},
    )
    assert main(["build", str(root), "aabb-river-light-2026"]) == 0

    after = read_article(paths.article_file(article_id))
    assert after.origin.type.value == "press_release"
    assert article_sentence_hash(before) == article_sentence_hash(after)

    run = load_corpus_run(paths)
    assert run.build_report["revised_articles"] == [article_id]
    assert run.build_report["anchor_delta"] == {}
    assert run.retexted_anchors == []

    out = capsys.readouterr().out
    assert "1 revised (record changed, sentences did not)" in out
    assert "no answer needs redoing" in out
    assert "re-annotate" not in out


def test_a_rewritten_sentence_keeps_its_address_and_is_reported(topic, capsys):
    """The one kind of anchor damage no downstream check can see.

    A removed sentence produces ``dangling_anchor``.  A sentence rewritten *in place* keeps
    its ``P{n}:S{n}``, so every gate passes and the published quote silently changes what it
    says.  Only the build sees both generations, so only the build can say which addresses
    moved.
    """
    root, paths = topic
    url = stage(paths, "cn-0001.yaml", body="第一句在这里。第二句在这里。")
    assert main(["build", str(root), "aabb-river-light-2026"]) == 0
    article_id = make_article_id("CN", url)

    paths.answers.parent.mkdir(parents=True, exist_ok=True)
    paths.answers.write_text("", encoding="utf-8")
    stage(paths, "cn-0001.yaml", body="第一句在这里。这一句完全换了说法。")
    assert main(["build", str(root), "aabb-river-light-2026"]) == 0

    run = load_corpus_run(paths)
    assert run.retexted_anchors == [f"{article_id}:P01:S02"]
    assert run.build_report["anchor_delta"][article_id]["retexted"] == ["P01:S02"]
    out = capsys.readouterr().out
    assert "silent drift" in out
    assert f"{article_id}: P01:S02" in out


def test_a_blank_line_declaration_over_a_single_newline_body_is_flagged(topic, capsys):
    """The collector declares the convention; the declaration itself must be checked.

    Both readings of the same bytes produce valid sentence IDs, so getting it wrong is
    silent: the whole article lands in P01 and every "which paragraph" answer is wrong while
    the corpus looks clean.
    """
    root, paths = topic
    body = "\n".join(f"第{n}段说了一些事情。" for n in range(1, 9))
    stage(paths, "cn-0001.yaml", body=body)
    assert main(["build", str(root), "aabb-river-light-2026"]) == 0
    out = capsys.readouterr().out
    assert "staged as paragraph_break=blank_line" in out
    assert "1 paragraph(s) that way and 8 as single_newline" in out


def test_a_short_one_paragraph_newsflash_is_not_flagged(topic, capsys):
    """The obvious false positive: a two-sentence wire flash has no newlines at all."""
    root, paths = topic
    stage(paths, "cn-0001.yaml", body="能矿部今天宣布了这项调整。该调整自周一起生效。")
    assert main(["build", str(root), "aabb-river-light-2026"]) == 0
    assert "paragraph_break=blank_line" not in capsys.readouterr().out


def test_labelling_a_whole_side_peripheral_blocks_the_build(topic, capsys):
    """A side can be silent; a side cannot be labelled out of existence unnoticed.

    ``silent_groups`` only fires at zero *clusters*.  A side with clusters, all of them
    peripheral, has independent reporting and an empty denominator at the same time — and
    before this check the build exited 0 and the page would have reported that the side
    addressed nothing.  Measured for real: a cheap relevance pass over a real corpus
    returned `peripheral` for all six Africa-side articles.
    """
    root, paths = topic
    stage(paths, "cn-0001.yaml", body=DISTINCT_BODIES[0])
    stage(paths, "us-0001.yaml", group_id="us", source_id="us_paper",
          lang="en", body="A first American sentence. A second American sentence.",
          topic_relevance="peripheral")
    stage(paths, "us-0002.yaml", group_id="us", source_id="us_paper",
          lang="en", body="A wholly separate American report. With its own second line.",
          topic_relevance="peripheral")

    assert main(["build", str(root), "aabb-river-light-2026"]) == 1
    out = capsys.readouterr().out
    assert "DENOMINATOR WIPEOUT — us" in out
    assert "This is not silence" in out
    # The run is still written and still restorable; what is refused is activation.


def test_a_cluster_read_only_as_title_and_lead_is_named_in_the_build_report(topic, capsys):
    """A paywalled cluster cannot answer questions; its silence is retrieval, not attention.

    Measured on aabb-market-meal-2024: 10 of 38 German clusters were captured title+lead only and
    0 of 30 Turkish ones, so the un-flagged reading was a 26-point one-sided hole that
    annotate meets as an unexplained low addressed rate and the reader meets as "the German
    press asked this less".
    """
    root, paths = topic
    stage(paths, "cn-0001.yaml", source_id="cn_agency", body=WIRE_BODY)
    stage(paths, "cn-0002.yaml", source_id="cn_paper_b", body=ORIGINAL_BODY,
          access_level="partial")

    assert main(["build", str(root), "aabb-river-light-2026"]) == 0

    out = capsys.readouterr().out
    assert "partial: cn has 1 of 2 cluster(s) captured as title+lead only" in out
    assert "retrieval, not attention" in out


def test_a_cluster_with_one_full_member_is_not_reported_as_title_and_lead_only(topic, capsys):
    """One readable member is enough: the cluster can answer, so it is not flagged."""
    root, paths = topic
    stage(paths, "cn-0001.yaml", source_id="cn_agency", body=WIRE_BODY)
    stage(paths, "cn-0002.yaml", source_id="cn_paper_a", body=WIRE_BODY, access_level="partial",
          origin={"type": "domestic_wire", "wire_source": "cn_agency"})

    assert main(["build", str(root), "aabb-river-light-2026"]) == 0

    assert "partial:" not in capsys.readouterr().out


def test_backfill_debt_rolls_forward_and_spends_its_budget(topic, capsys):
    """A debt is a ledger entry — it survives builds that say nothing about it,
    spends a retry round on --retry-debt, and leaves only through --close-debt."""
    root, paths = topic
    stage(paths, "cn-0001.yaml", body=DISTINCT_BODIES[0])
    assert main(["build", str(root), "aabb-river-light-2026",
                 "--backfill-debt", "us_paper:policy_name:engine walled before the grid re-ran"]) == 0
    run = load_corpus_run(paths)
    assert [(d.key, d.retries, d.budget_exhausted) for d in run.backfill_debt] == [
        ("us_paper:policy_name", 0, False)
    ]

    # An extend that says nothing about the debt still carries it (the aabb-garden-wind-2026
    # lesson: not restating a debt must not shed it).
    stage(paths, "cn-0002.yaml", body=DISTINCT_BODIES[1])
    assert main(["build", str(root), "aabb-river-light-2026"]) == 0
    run = load_corpus_run(paths)
    assert [(d.key, d.retries) for d in run.backfill_debt] == [("us_paper:policy_name", 0)]
    assert any(w.startswith("backfill debt:") for w in run.warnings)

    # A failed targeted retry spends one round of the budget.
    stage(paths, "cn-0003.yaml", body=DISTINCT_BODIES[2])
    assert main(["build", str(root), "aabb-river-light-2026",
                 "--retry-debt", "us_paper:policy_name"]) == 0
    run = load_corpus_run(paths)
    assert [(d.key, d.retries) for d in run.backfill_debt] == [("us_paper:policy_name", 1)]
    assert not run.backfill_debt[0].budget_exhausted

    # Closing removes it; nothing rolls into the next run.
    stage(paths, "cn-0004.yaml", body=ORIGINAL_BODY)
    assert main(["build", str(root), "aabb-river-light-2026",
                 "--close-debt", "us_paper:policy_name"]) == 0
    assert load_corpus_run(paths).backfill_debt == []


def test_futile_debt_is_spent_at_birth_and_flags_are_validated(topic, capsys):
    root, paths = topic
    stage(paths, "cn-0001.yaml", body=DISTINCT_BODIES[0])
    assert main(["build", str(root), "aabb-river-light-2026",
                 "--backfill-debt", "us_paper:all-cells:subscription wall survived both layers",
                 "--futile-debt", "us_paper:all-cells"]) == 0
    run = load_corpus_run(paths)
    assert run.backfill_debt[0].retry_futile and run.backfill_debt[0].budget_exhausted

    # The flags refuse a debt that does not exist, and a re-declaration of one that does.
    stage(paths, "cn-0002.yaml", body=DISTINCT_BODIES[1])
    assert main(["build", str(root), "aabb-river-light-2026",
                 "--close-debt", "nobody:nowhere"]) == 2
    assert "no such debt" in capsys.readouterr().err
    assert main(["build", str(root), "aabb-river-light-2026",
                 "--retry-debt", "nobody:nowhere"]) == 2
    assert "no such debt" in capsys.readouterr().err
    assert main(["build", str(root), "aabb-river-light-2026",
                 "--backfill-debt", "us_paper:all-cells:restated"]) == 2
    assert "already owed" in capsys.readouterr().err

    # A futile debt still rolls forward — spent, not forgotten — until closed.
    assert main(["build", str(root), "aabb-river-light-2026"]) == 0
    run = load_corpus_run(paths)
    assert [(d.key, d.retry_futile) for d in run.backfill_debt] == [("us_paper:all-cells", True)]
