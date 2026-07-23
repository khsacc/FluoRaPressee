---
sidebar_position: 4
title: API連携
description: HTTP APIの起動方法と利用上の注意
---

# API連携

FluoRaPresseeは、同一LAN内の別PCからHTTP経由で測定を実行できるAPIモードを
備えています。

## 起動方法

1. GUIで較正、ROI、分光器設定を完了します。
2. `API Server`パネルでポート番号を指定します（既定値：`8765`）。
3. `Start API Server`を押します。
4. 画面に表示されるURLとAPIキーを確認します。

APIサーバーの起動中は、競合を防ぐためGUIの測定・設定操作がロックされます。

## APIドキュメント

サーバー起動後、次のURLでSwagger UIを確認できます。

```text
http://<FluoRaPresseeを実行しているPCのIP>:8765/docs
```

APIリクエストでは、原則として次のヘッダーが必要です。

```http
X-API-Key: <画面に表示されたAPIキー>
```

詳細なエンドポイント仕様は、リポジトリ内の
[APIリファレンス](https://github.com/khsacc/FluoRaPressee/blob/main/manuals/API.md)
を参照してください。
