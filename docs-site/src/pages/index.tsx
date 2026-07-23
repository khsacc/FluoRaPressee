import type {ReactNode} from 'react';
import clsx from 'clsx';
import Link from '@docusaurus/Link';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import Layout from '@theme/Layout';
import Heading from '@theme/Heading';

import styles from './index.module.css';

function HomepageHeader() {
  const {siteConfig} = useDocusaurusContext();
  return (
    <header className={clsx('hero hero--primary', styles.heroBanner)}>
      <div className="container">
        <Heading as="h1" className="hero__title">
          {siteConfig.title}
        </Heading>
        <p className="hero__subtitle">{siteConfig.tagline}</p>
        <div className={styles.buttons}>
          <Link
            className="button button--secondary button--lg"
            to="/docs/">
            マニュアルを読む
          </Link>
        </div>
      </div>
    </header>
  );
}

export default function Home(): ReactNode {
  const {siteConfig} = useDocusaurusContext();
  return (
    <Layout
      title="オンラインマニュアル"
      description="分光測定・解析ソフトウェア FluoRaPressee のオンラインマニュアル">
      <HomepageHeader />
      <main>
        <section className={styles.overview}>
          <div className="container">
            <div className="row">
              <div className="col col--4">
                <Heading as="h2">測定</Heading>
                <p>Andor、Princeton Instruments、Ocean Opticsの装置構成に対応します。</p>
              </div>
              <div className="col col--4">
                <Heading as="h2">解析</Heading>
                <p>較正、バックグラウンド補正、ピークフィット、圧力計算を一つのGUIで行えます。</p>
              </div>
              <div className="col col--4">
                <Heading as="h2">連携</Heading>
                <p>HTTP APIを使用して、同一LAN内の別PCから測定を自動化できます。</p>
              </div>
            </div>
          </div>
        </section>
      </main>
    </Layout>
  );
}
