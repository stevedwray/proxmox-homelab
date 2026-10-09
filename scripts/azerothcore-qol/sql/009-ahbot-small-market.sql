-- Apply after mod-ah-bot's supplied mod_auctionhousebot.sql.
-- Keep a deliberately small seller-only market for a two-human LAN realm.

UPDATE mod_auctionhousebot
SET minitems = 100, maxitems = 100
WHERE auctionhouse IN (2, 6);

UPDATE mod_auctionhousebot
SET minitems = 60, maxitems = 60
WHERE auctionhouse = 7;
