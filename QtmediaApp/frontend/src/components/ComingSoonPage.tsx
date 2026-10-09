export function ComingSoonPage({ title }: { title: string }) {
  return (
    <section className="coming-soon page-panel" aria-labelledby="coming-title">
      <p className="eyebrow">Coming next</p>
      <h1 id="coming-title">{title}</h1>
      <p>This space is ready for the next Qtmedia milestone.</p>
    </section>
  );
}
