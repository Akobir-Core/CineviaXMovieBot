from __future__ import annotations


async def recommend(db, user_id: int, limit: int = 8):
    # Deterministic recommendation: score real database signals only.
    genre_rows = await db.fetchall("""
        SELECT genre_id, SUM(weight) score FROM (
            SELECT m.genre_id, 5 weight FROM favorites f JOIN movies m ON f.content_kind='movie' AND f.content_id=m.id WHERE f.user_id=? AND m.genre_id IS NOT NULL
            UNION ALL SELECT s.genre_id, 5 FROM favorites f JOIN series s ON f.content_kind='series' AND f.content_id=s.id WHERE f.user_id=? AND s.genre_id IS NOT NULL
            UNION ALL SELECT m.genre_id, 4 FROM watch_history h JOIN movies m ON h.content_kind='movie' AND h.content_id=m.id WHERE h.user_id=? AND m.genre_id IS NOT NULL
            UNION ALL SELECT s.genre_id, 4 FROM watch_progress p JOIN series s ON p.series_id=s.id WHERE p.user_id=? AND s.genre_id IS NOT NULL
        ) q GROUP BY genre_id ORDER BY score DESC, genre_id LIMIT 10
    """, (user_id,user_id,user_id,user_id))
    genre_scores={int(r['genre_id']):int(r['score']) for r in genre_rows if r['genre_id'] is not None}
    favorite_types = {str(r['content_kind']) for r in await db.fetchall("SELECT DISTINCT content_kind FROM favorites WHERE user_id=?",(user_id,))}

    movie_rows = await db.fetchall("""SELECT m.id,m.title,m.code,m.content_type,m.release_year,m.views_count,'movie' kind,m.genre_id,m.created_at,m.featured FROM movies m WHERE m.active=1 AND m.visibility='public'""")
    series_rows = await db.fetchall("""SELECT s.id,s.title,s.code,s.content_type,s.release_year,s.views_count,'series' kind,s.genre_id,s.created_at,s.featured FROM series s WHERE s.active=1 AND s.visibility='public'""")
    rows=list(movie_rows)+list(series_rows)
    scored=[]
    for r in rows:
        score=0
        score += genre_scores.get(int(r['genre_id']),0) if r['genre_id'] is not None else 0
        if r['kind'] in favorite_types: score += 3
        score += min(int(r['views_count'] or 0),50)//10
        score += 2 if r['featured'] else 0
        # modest recency bonus measured by rank-like date string, without external data.
        scored.append((score,r))
    scored.sort(key=lambda x:(x[0], x[1]['created_at'], int(x[1]['id'])), reverse=True)
    result=[]; seen=set()
    for _,r in scored:
        key=(r['kind'],int(r['id']))
        if key in seen: continue
        seen.add(key); result.append(r)
        if len(result)>=limit: break
    return result
