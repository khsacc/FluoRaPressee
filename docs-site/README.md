# FluoRaPressee Manual

This website is built using [Docusaurus](https://docusaurus.io/), a modern static website generator.

FluoRaPresseeのオンラインマニュアルを生成するDocusaurusプロジェクトです。

## セットアップ

```bash
npm ci
```

**Note**: feel free to use the package manager of your choice.

Node.js 20以上が必要です。

## ローカル開発

```bash
npm run start
```

`http://localhost:3000/FluoRaPressee/`でプレビューできます。

## ビルド

```bash
npm run build
```

生成物は`build/`に出力されます。`main`ブランチへのpush時には、
リポジトリルートのGitHub ActionsからGitHub Pagesへ自動公開されます。
