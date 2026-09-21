import { Icon } from "@/components/identity";

/**
 * Reserved home for autonomous jobs (OpenClaw, Telegram remote jobs, scheduled
 * maintenance, PC control). Deliberately kept off the default HUD until those
 * capabilities exist - this is a placeholder destination, not a feature.
 */
export function AutonomyHub() {
  return (
    <div className="absolute-panel autonomy-hub">
      <div className="panel-intro">
        <span className="eyebrow">AUTONOMY / RESERVED</span>
        <h3>Otonom yetenekler yakında.</h3>
        <p>
          OpenClaw, Telegram üzerinden uzaktan görevler, zamanlanmış bakım ve PC kontrolü gibi otonom yetenekler
          buraya taşınacak. Ana ekranı meşgul etmeyecekler - onları açtığında sadece burada, açıkça çağırdığında
          çalışacaklar.
        </p>
      </div>
      <div className="autonomy-empty">
        <Icon name="autonomy" />
        <strong>Henüz bir otonom görev yok.</strong>
        <span>Bu bölüm hazır olduğunda gerçek görevler burada listelenecek.</span>
      </div>
    </div>
  );
}
