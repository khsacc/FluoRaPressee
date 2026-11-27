---
name: fluorapressee-release
description: このリポジトリ（khsacc/FluoRaPressee）の Windows インストーラーを GitHub Actions で配布する。__dev のベータ配布、PR マージ後の master の正式版、リリースタグの作成と push、下書きの確認と公開、失敗したビルドの再試行に使う。
---

# FluoRaPressée のリリース

このタスクは `khsacc/FluoRaPressee` のチェックアウトで使う。作業前にリポジトリのルートと `origin` の fetch・push 先を確認し、対象が一致したらルートの `AGENTS.md` と `.github/workflows/release.yml` を読む。Mac ではアプリやリポジトリのテストを実行せず、Windows 用 CI に任せる。

## 対象コミットとバージョン

| 依頼 | タグ付け対象 | 版の例 |
| --- | --- | --- |
| dev のプレリリース | `origin/__dev`。別の開発ブランチはユーザーが明示した場合に使う | `0.1.0b1` → `v0.1.0b1` |
| 正式リリース | リリース対象の PR が取り込まれた後の `origin/master` | `0.1.0` → `v0.1.0` |

1. リモートを fetch し、公開対象のコミットを SHA で特定する。正式版では PR のマージと対象変更が `master` に入っていることを確認する。ここでの「dev」は通常 `__dev` を指す。
2. タグ付けするコミット自身の `src/version.py` と `.github/workflows/release.yml` を `git show` などで確認する。タグは `v` に `__version__` をそのまま続ける。版の種別は PEP 440 に基づいて CI が判定する。希望の版や種別と違う場合は先に版を直したコミットを対象ブランチに反映する。正式版の変更も通常の PR 経由とし、対象変更のマージ前はタグを作成しない。
3. ローカルタグと GitHub 側の同名タグを確認する。注釈付きタグはタグオブジェクトではなく参照先のコミット SHA を比較する。既存タグが同じコミットを指す場合は再利用する。すでに GitHub にある場合は既存の CI 実行とリリースの状態を確認する。別コミットを指す場合は「失敗時」の手順を使う。

## ビルドと公開

- タグの push またはビルドを依頼されたら、確認した SHA に `git tag -a "$tag" "$release_commit" -m "FluoRaPressée $version"` で注釈付きタグを作り、`git push origin "refs/tags/$tag"` で対象タグだけを送る。PR のマージとブランチの push ではこの CI は起動しない。
- GitHub Actions の **Release build** で、対象タグと SHA の実行が開始されたことを確認する。例は `gh run list --repo khsacc/FluoRaPressee --workflow release.yml --branch "$tag" --event push`。CLI に認証がない場合、公開リポジトリの Actions 実行は GitHub REST API でも確認できる。
- 通常のリリース依頼はビルド開始の確認で作業を終了してよい。対象バージョン、コミット SHA、実行 URL、確認時点のステータスと、下記のビルド完了後の手順を案内する。CI の完了を待ったり、繰り返し進捗を監視したりする必要はない。ユーザーが明示的に完了までの監視を依頼した場合のみ、結果まで追う。
- CI は Windows でテストとインストーラー作成を行い、成功すると `FluoRaPressee-Setup-<version>.exe` を添付した下書きを自動作成する。開始確認時点では、ビルド成功・下書き作成・公開が済んだとは報告しない。

## ビルド完了後に案内する手順

1. 実行 URL で CI の成功を確認し、GitHub Releases の対象タグの下書きを開く。失敗した場合はログを確認し、下記の「失敗時」に従う。
2. タグ、プレリリース設定、添付ファイル `FluoRaPressee-Setup-<version>.exe` を確認する。
3. **Changes / 変更点** を実際の変更点に置き換え、配布するインストーラーを Windows 実機で確認する。
4. 確認後、Web の **Publish release** または認証済みの `gh release edit "$tag" --repo khsacc/FluoRaPressee --draft=false` で公開し、リリース URL と添付ファイルを確認する。

CI 完了後に下書きの編集・公開を依頼された場合は、この手順に沿って作業する。

## 失敗時

- 一時的な失敗でソース修正が不要なら、失敗した実行を再試行する。再実行は元のコミットを使う。
- 修正後のコミットを使う場合、未公開のベータなら同じ番号で再ビルドできる。既存の下書きとタグの状態を確認し、古い下書きの削除やタグの付け直しは、ユーザーがその操作を明示的に依頼した場合に行う。タグ付け直し後は新しい SHA の CI 実行を確認する。
- 公開済みの版を修正する場合は、より新しい版を使う。例は `0.1.0b1` → `0.1.0b2`。`master` の正式リリースも、公開済みのタグは保持する。
