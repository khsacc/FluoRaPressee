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
- GitHub Actions の **Release build** で、対象タグと SHA の実行を確認する。例は `gh run list --repo khsacc/FluoRaPressee --workflow release.yml --branch "$tag" --event push`。CLI に認証がない場合、公開リポジトリの Actions 実行は GitHub REST API でも確認できる。開始だけの依頼ならステータスと実行 URL を返す。完了や公開までの依頼なら CI の結果まで追う。
- CI は Windows でテストとインストーラー作成を行い、成功すると `FluoRaPressee-Setup-<version>.exe` を添付した下書きを作る。ビルドの依頼では下書きまでを扱う。
- 公開の依頼があるときは、対象タグ、下書きのプレリリース設定、添付ファイル名を確認する。**Changes / 変更点** を実際の変更点に置き換え、配布するインストーラーの Windows 実機確認が済んでいることを確認してから公開する。Web の **Publish release** または認証済みの `gh release edit "$tag" --repo khsacc/FluoRaPressee --draft=false` を使える。公開後はリリース URL と添付ファイルを確認する。

## 失敗時

- 一時的な失敗でソース修正が不要なら、失敗した実行を再試行する。再実行は元のコミットを使う。
- 修正後のコミットを使う場合、未公開のベータなら同じ番号で再ビルドできる。既存の下書きとタグの状態を確認し、古い下書きの削除やタグの付け直しは、ユーザーがその操作を明示的に依頼した場合に行う。タグ付け直し後は新しい SHA の CI 実行を確認する。
- 公開済みの版を修正する場合は、より新しい版を使う。例は `0.1.0b1` → `0.1.0b2`。`master` の正式リリースも、公開済みのタグは保持する。
