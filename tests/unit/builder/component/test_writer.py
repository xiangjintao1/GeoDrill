# -*- coding: utf-8 -*-
# Copyright 2026 向金涛
# Affiliation: 吉林大学
from kag.interface import SinkWriterABC
from kag.common.conf import KAG_PROJECT_CONF


def test_writer():
    conf = {
        "type": "kg",
    }

    writer = SinkWriterABC.from_config(conf)
    from kag.builder.component.writer.kg_writer import KGWriter

    assert isinstance(writer, KGWriter)
    assert writer.project_id == KAG_PROJECT_CONF.project_id

    conf = {
        "type": "kg",
        "project_id": 888,
    }
    writer = SinkWriterABC.from_config(conf)
    assert writer.project_id == 888
