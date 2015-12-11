#!/bin/python2.7
# -*- coding: utf-8 -*-
"""Převod GML s ruianem do mongodb
"""

from lxml import objectify, etree
import lxml
import simplejson as json
from osgeo import ogr, osr
from pymongo import MongoClient

import os, sys
import argparse

class d2(dict):
    """Rozšíření pole o fci, která místo update přidá hodnotu do pole k
    již vložené hodnotě
    :param dict: dict
    :return: dict
    """
    #kvuli pridavani hodnot co maj klic, kterej uz tam je
    def addval(self, newkey, newval):
        """když klíč ve stávajícím poli není, udělá se update,
        když tam je, udělá se ze stávající a nové hodnoty pole
        když je stávající hodnota pole, tak se nová hodnota appendne
        :param newkey: klíč vkládané hodnoty
        :param newval: vkládaná hodnota
        :return: aktualizovaný dict
        """
        if not newkey in self:
            self.update({newkey:newval})

        else:
            if type(self[newkey]) is list:
                self[newkey].append(newval)

            else:
                self[newkey] = [self[newkey], newval]

        return(self)

class mongolizer(dict):
    """nahrne ruiani prvek do slovniku, který má strukturu korektního geojsonu
    :param feat: je uzel lxml objectify odpovídající jednomu prvku (obec, parcela,
    ulice apod...)
    :return: dict, který se dá vložit přes pymongo, nebo pomocí simplejson.dumps 
    převést na korektní geojson
    """
    def __init__(self, feat):
        """nahrne ruiani prvek do slovniku, který má strukturu korektního geojsonu
        :param feat: je uzel lxml objectify odpovídající jednomu prvku (obec, parcela, 
        ulice apod...)
        :return: dict, který se dá vložit přes pymongo, nebo pomocí simplejson.dumps 
        převést na korektní geojson
        """
        self.update({"type":"Feature"})
        #pridej proprty
        self['properties'] = mongolizer.mongolizuj_proprty(feat)
        #pridej geosku
        self.update(mongolizer.mongolizuj_geometrie(feat))
        #pridej pk
        self['_id'] = int(feat.get('{http://www.opengis.net/gml/3.2}id').split('.')[1])

    @staticmethod
    def mongolizuj_proprty(feat):
        """převede elementy (atributy) kromě geometrií na slovník
        :param feat: je uzel lxml objectify odpovídající jednomu prvku (obec, 
        parcela, ulice apod...)
        :return: dict odpovídající hodnotě properties v geojsonu
        """
        #udělá z objektu jeesona, co se bude dat do monga
        #inspirace zde
        #https://gist.github.com/aisipos/345559
        proprty=d2({})

        for prop in feat.iterchildren():
            #pro vsechny polozky
            #jestli je to localname geometrie, tak updatuj ret tim co vrati geometrie do jsonu
            if etree.QName(prop).localname == 'Geometrie': ##tohle budu muset udelat jinde, abych oddelil proprty
                #ret.update(geometrii_do_geojsonu(prop))
                pass

            elif isinstance(prop, lxml.objectify.IntElement):
                proprty.addval(etree.QName(prop).localname,  int(prop))

            elif (isinstance(prop, lxml.objectify.NumberElement) or 
            isinstance(prop, lxml.objectify.FloatElement)):
                proprty.addval(etree.QName(prop).localname,  float(prop))

            elif isinstance(prop, lxml.objectify.ObjectifiedDataElement):
                proprty.addval(etree.QName(prop).localname,  prop.text) 
                #str(prop)) tohle dela bordel, neco s kodovanim

            else:
                proprty.addval(etree.QName(prop).localname,  
                        mongolizer.mongolizuj_proprty(prop))

        return(proprty)

    @staticmethod
    def mongolizuj_geometrie(i):
        """převede geometrie z GML na slovník se strukturou geojson a transformuje 
        do WGS
        :param feat: je uzel lxml objectify odpovídající jednomu prvku (obec, 
        parcela, ulice apod...)
        :return: dict geometrií
        """
        srs5514 = osr.SpatialReference()
        srs5514.ImportFromWkt("""
        PROJCS["S-JTSK / Krovak East North",
            GEOGCS["S-JTSK",
                DATUM["System_Jednotne_Trigonometricke_Site_Katastralni",
                    SPHEROID["Bessel 1841",6377397.155,299.1528128,
                        AUTHORITY["EPSG","7004"]],
                    TOWGS84[570.8,85.7,462.8,4.998,1.587,5.261,3.56],
                    AUTHORITY["EPSG","6156"]],
                PRIMEM["Greenwich",0,
                    AUTHORITY["EPSG","8901"]],
                UNIT["degree",0.0174532925199433,
                    AUTHORITY["EPSG","9122"]],
                AUTHORITY["EPSG","4156"]],
            PROJECTION["Krovak"],
            PARAMETER["latitude_of_center",49.5],
            PARAMETER["longitude_of_center",24.83333333333333],
            PARAMETER["azimuth",30.28813972222222],
            PARAMETER["pseudo_standard_parallel_1",78.5],
            PARAMETER["scale_factor",0.9999],
            PARAMETER["false_easting",0],
            PARAMETER["false_northing",0],
            UNIT["metre",1,
                AUTHORITY["EPSG","9001"]],
            AXIS["X",EAST],
            AXIS["Y",NORTH],
            AUTHORITY["EPSG","5514"]] 
            """)

        srs4326 = osr.SpatialReference()
        srs4326.ImportFromEPSG(4326)

        transform = osr.CoordinateTransformation(srs5514, srs4326)


        #g=i.xpath("*[local-name()='Geometrie']")[0]
        g=[e for e in i.getchildren() if etree.QName(e).localname == 'Geometrie']
        if len(g) == 0:
            #chybi geometrie
            return({})

        g = g[0]
        ret={}
        if hasattr(g, 'OriginalniHranice'):
            gml = etree.tostring(g.OriginalniHranice.getchildren()[0])
            geom = ogr.CreateGeometryFromGML(gml)
            geom.Transform(transform)
            if hasattr(geom, 'HasCurveGeometry') and\
                    geom.HasCurveGeometry():
                geom = geom.GetLinearGeometry(dfMaxAngleStepSizeDegrees=10) #max angle in arc

            #validation
            #tohle nekde pomuze a nekde zaskodi
            if not geom.IsValid():
                geom = geom.Buffer(0) #s nulou to zere geom
            ret['geometry'] = json.loads(geom.ExportToJson())

        if hasattr(g, 'DefinicniBod'):
            defbod = g.DefinicniBod

            #osetri adresni mista
            if hasattr(defbod, 'AdresniBod'):
                gml = etree.tostring(defbod.AdresniBod.getchildren()[0])

            else:
                gml = etree.tostring(defbod.getchildren()[0])


            geom = ogr.CreateGeometryFromGML(gml)
            geom.Transform(transform)
            #on point geom not necessary
            #if hasattr(geom, 'HasCurveGeometry') and\
            #        geom.HasCurveGeometry():
            #    geom = geom.GetLinearGeometry()

            #valid
            if not geom.IsValid():
                geom = geom.Buffer(0)
            ret['geometry_p'] = json.loads(geom.ExportToJson())

        if hasattr(g, 'DefinicniCara'):
            gml = etree.tostring(g.DefinicniCara.getchildren()[0])
            geom = ogr.CreateGeometryFromGML(gml)
            geom.Transform(transform)
            if hasattr(geom, 'HasCurveGeometry') and\
                    geom.HasCurveGeometry():
                geom = geom.GetLinearGeometry()
            ret['geometry_l'] = json.loads(geom.ExportToJson())


        return(ret)


def parse_layer(lay, db):
    """projde vrstvu z ruian GML (Obce, Parcely, StavebniObjekty atp...)
    a překlopí je do monga, používá lxml, možná že u větších souborů (Praha bude 
    třeba použít něco jinýho
    :param lay: uzel objectify root.Data.getchildren()[n]
    :param db: mongo databáze MongoClent().dbname
    """
    ##tady mozna bude treba pouzit neco jinyho nez dom
    ##prochazi vrstvu prvek po prvku
    layername = etree.QName(lay).localname
    print(layername)
    collection = db[layername]
    for feat in lay.iterchildren():
        #pro kazdej prvek
        #udela z prvku json a posle do monga
        #print(mongolizer(feat))
        print(collection.insert_one(mongolizer(feat)).inserted_id)


def main():

    parser = argparse.ArgumentParser(description='Mongolizuje ruian data')
    parser.add_argument('--ruian_file', help='Ruian file', required=True)
    parser.add_argument('--db', help='Mongo databaze', required=True)

    args = parser.parse_args()

    if not os.path.isfile(args.ruian_file):
        logging.error('Ruian file %s is not file' %  args.ruian_file)
        sys.exit(1)

    # parse command line options
    f = open(args.ruian_file,'r');

    doc = objectify.parse(f)
    root = doc.getroot()
    data = root.Data

    client = MongoClient('localhost', 27017) #klient na mongo
    db = client[args.db]

    for layer in data.iterchildren(): 
        ##tady mozna bude treba pouzit neco jinyho nez dom
        parse_layer(layer, db)

if __name__ == "__main__":
    main()
