# Crossover

İki kişilik online futbol düellosu. İki oyuncu birer kulüp seçer (10, 15 ya da 20 saniye); iki kulüpte de oynamış bir futbolcuyu ilk yazan turu alır. Türkçe ve İngilizce.

A two-player online football duel. Each player picks a club (10, 15 or 20 seconds); the first to name a footballer who played for both clubs wins the round. Turkish and English.

**Oyna / Play:** https://yessir03.github.io/crossover/

- Oyuncu verisi / player data: [Wikidata](https://www.wikidata.org) (CC0)
- Online eşleşme / matchmaking: Supabase Realtime (presence + broadcast)

## Oyuncu verisi nasıl güncelleniyor / How the player data is updated

- `scripts/update_data.py` 65 kulübün oyuncularını iki kaynaktan çeker: Wikidata kulüp kayıtları ve Wikipedia'nın "<Kulüp> oyuncuları" kategorileri (İngilizce, Türkçe ve 10 dil daha). Sonra `data/players.txt` dosyasını yazar ve oyunun içine (`index.html`) yerleştirir.
- `.github/workflows/update-data.yml` bunu **her ayın 1'inde** otomatik çalıştırır. Transfer döneminden hemen sonra güncellemek için GitHub'da **Actions → Oyuncu verisini güncelle → Run workflow**.
- Wikidata'da eksik bir transfer varsa `data/extra.txt` dosyasına `Oyuncu Adı|Kulüp,Kulüp` satırı ekle; bir sonraki güncellemede oyuna girer.
