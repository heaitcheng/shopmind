from app.schemas import AfterSaleIntent, AfterSaleRequest


def test_抽取接口返回结构化字段(client, fake_model):
    fake_model.structured_result = AfterSaleRequest(
        order_id="SO20261029001",
        intent=AfterSaleIntent.EXCHANGE,
        reason="尺码太小",
        expected_solution="换 L 码",
        missing_fields=[],
        confidence=0.85,
    )

    r = client.post(
        "/api/chat/extract",
        json={"text": "昨天买的衣服太小了，订单号 SO20261029001，想换成 L 码"},
    )

    assert r.status_code == 200
    body = r.json()
    assert body["order_id"] == "SO20261029001"
    assert body["intent"] == "exchange"
    assert body["confidence"] == 0.85


def test_抽取接口透传原文给模型(client, fake_model):
    fake_model.structured_result = AfterSaleRequest(intent=AfterSaleIntent.OTHER)

    client.post("/api/chat/extract", json={"text": "随便问一句"})

    assert fake_model.last_extract_messages[-1].content == "随便问一句"


def test_抽取缺少text返回422(client):
    assert client.post("/api/chat/extract", json={}).status_code == 422
