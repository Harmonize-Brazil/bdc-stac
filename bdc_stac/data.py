import sqlalchemy
import os
from collections import OrderedDict
from datetime import datetime
from copy import deepcopy


def get_collection_items(collection_id=None, item_id=None, bbox=None, time=None, ids=None, collections=None):
    sql = f"SELECT p.`datacube`, p.`tileid`, p.`start`, p.`end`, p.`type`, p.`sceneid`, p.`band`, p.`cloud`, " \
        f"p.`processingdate`, p.`TL_Latitude`, p.`TL_Longitude`, p.`BR_Latitude`, p.`BR_Longitude`, p.`TR_Latitude`, " \
        f"p.`TR_Longitude`, p.`BL_Latitude`, p.`BL_Longitude`, p.`filename`, q.`qlookfile` FROM `products`" \
        f" AS p, `qlook` AS q WHERE "

    where = list()

    where.append(f"p.`sceneid` = q.`sceneid`")

    if ids is not None:
        where.append(f"FIND_IN_SET(p.`sceneid`, '{ids}')")
    elif item_id is not None:
        where.append(f"p.`sceneid` LIKE '{item_id}'")
    else:
        if collections is not None:
            where.append(f"FIND_IN_SET(p.`datacube`, '{collections}')")
        elif collection_id is not None:
            where.append(f"p.`datacube` LIKE '{collection_id}'")

        if bbox is not None:
            try:
                for x in bbox.split(','):
                    float(x)
                min_x, min_y, max_x, max_y = bbox.split(',')

                bbox = ""
                bbox += "(({} <= p.`TR_Longitude` and {} <= p.`TR_Latitude`)".format(min_x, min_y)
                bbox += " or "
                bbox += "({} <= p.`BR_Longitude` and {} <= p.`TL_Latitude`))".format(min_x, min_y)
                bbox += " and "
                bbox += "(({} >= p.`BL_Longitude` and {} >= p.`BL_Latitude`)".format(max_x, max_y)
                bbox += " or "
                bbox += "({} >= p.`TL_Longitude` and {} >= p.`BR_Latitude`))".format(max_x, max_y)

                where.append("(" + bbox + ")")
            except:
                raise (InvalidBoundingBoxError())

        if time is not None:
            if "/" in time:
                time_start, end = time.split("/")
                time_end = datetime.fromisoformat(end)
                where.append(f"`end` < '{time_end}'")
            else:
                time_start = datetime.fromisoformat(time)
            where.append(f"`start` > '{time_start}'")

    where = " AND ".join(where)

    group = f" GROUP by  p.`datacube`, p.`tileid`, p.`start`, p.`end`, p.`type`, p.`sceneid`, p.`band`, p.`cloud`, " \
        f"p.`processingdate`, p.`TL_Latitude`, p.`TL_Longitude`, p.`BR_Latitude`, p.`BR_Longitude`, p.`TR_Latitude`, " \
        f"p.`TR_Longitude`, p.`BL_Latitude`, p.`BL_Longitude`, p.`filename`, q.`qlookfile` " \
        f"ORDER by p.`sceneid`"

    sql += where + group
    items = do_query(sql)

    return items


def get_collection(collection_id):
    sql = f"SELECT `datacube` AS id, start, end, bands, satsen from `datacubes` WHERE `datacube` LIKE '{collection_id}'"


    extent = do_query(f"SELECT CONCAT_WS(',', MIN(BL_Latitude),MIN(BL_Longitude),MAX(TR_Longitude),"
                      f"MAX(TR_Latitude)) AS extent FROM `products` WHERE `datacube` LIKE '{collection_id}'")

    collection = do_query(sql)

    start = datetime.fromisoformat(str(collection['start'])).astimezone().isoformat()
    end = None if collection['end'] is None else datetime.fromisoformat(str(collection['end'])).astimezone().isoformat()

    collection["stac_version"] = os.getenv("API_VERSION")
    collection["description"] = f"{collection_id} datacube with products from" \
        f" {collection['satsen']}(Sattelite/Sensor) with {collection['bands']} bands."

    collection["license"] = None
    # collection["properties"] = {}
    collection["extent"] = {"spatial": extent["extent"].split(','), "time": [start, end]}

    collection.pop('bands')
    collection.pop('satsen')
    collection.pop('start')
    collection.pop('end')

    return collection


def get_collections():
    sql = "SELECT  datacube FROM  `datacubes`"
    datacubes = do_query(sql)

    return datacubes


def make_geojson(items, links, page=1, limit=10):
    features = []

    last = ''
    feature = None

    for i in items:
        if last != i['sceneid']:
            last = i['sceneid']

            feature = OrderedDict()

            feature['type'] = 'Feature'
            feature['id'] = i['sceneid']
            feature['collection'] = i['datacube']

            geometry = OrderedDict()
            geometry['type'] = 'Polygon'
            geometry['coordinates'] = [
                [[i['TL_Longitude'], i['TL_Latitude']],
                 [i['BL_Longitude'], i['BL_Latitude']],
                 [i['BR_Longitude'], i['BR_Latitude']],
                 [i['TR_Longitude'], i['TR_Latitude']],
                 [i['TL_Longitude'], i['TL_Latitude']]]
            ]
            feature['bbox'] = bbox(geometry['coordinates'])
            feature['geometry'] = geometry

            properties = OrderedDict()

            start = datetime.fromisoformat(str(i['start'])).astimezone().isoformat()
            end = "null" if i['end'] is None else datetime.fromisoformat(str(i['end'])).astimezone().isoformat()

            properties['datetime'] = f"{start}/{end}"

            feature['properties'] = properties

            assets = OrderedDict()
            assets['thumbnail'] = {'href': os.getenv('FILE_ROOT') + i['qlookfile']}
            feature['assets'] = assets
            feature['links'] = deepcopy(links)
            feature['links'][0]['href'] += i['datacube']+"/items/"+i['sceneid']
            feature['links'][1]['href'] += i['datacube']
            feature['links'][2]['href'] += i['datacube']
            features.append(feature)
        features[-1]['assets'][i['band']] = {'href': os.getenv('FILE_ROOT') + i['filename']}
    if len(features) == 1:
        return features[0]

    gjson = OrderedDict()
    gjson['type'] = 'FeatureCollection'

    p = (page - 1) * limit + limit
    min, max = (page - 1) * limit, \
               len(features) if p > len(features) else p

    gjson['features'] = features[min:max]

    return gjson


def do_query(sql):
    connection = 'mysql://{}:{}@{}/{}'.format(os.environ.get('DB_USER'),
                                              os.environ.get('DB_PASS'),
                                              os.environ.get('DB_HOST'),
                                              os.environ.get('DB_NAME'))
    engine = sqlalchemy.create_engine(connection)
    result = engine.execute(sql)
    result = result.fetchall()
    engine.dispose()
    result = [dict(row) for row in result]
    return result if len(result) > 1 else result[0]


def bbox(coord_list):
    box = []
    for i in (0, 1):
        res = sorted(coord_list[0], key=lambda x: x[i])
        box.append((res[0][i], res[-1][i]))
    ret = [box[0][0], box[1][0], box[0][1], box[1][1]]
    return ret


class InvalidBoundingBoxError(Exception):
    pass
