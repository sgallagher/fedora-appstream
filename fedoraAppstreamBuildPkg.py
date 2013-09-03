#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Licensed under the GNU General Public License Version 2
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.

# Copyright (C) 2009-2013
#    Richard Hughes <richard@hughsie.com>
#

import ConfigParser
import glob
from PIL import Image
import os
import shutil
import subprocess
import sys
import tarfile

import yum
from yum.packages import YumLocalPackage, parsePackages

import cairo
import rsvg

import fedoraAppstreamData

# NOTE; we could use escape() from xml.sax.saxutils import escape but that seems
# like a big dep for such trivial functionality
def sanitise_xml(text):
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text

def resize_icon(icon):
    
    # use PIL to resize PNG files
    if icon.endswith('.png'):
        im = Image.open(icon)
        width, height = im.size
        if width <= 64 and height <= 64:
            return icon
        im = im.resize((64, 64), Image.ANTIALIAS)
        icon_fullpath = '/tmp/image.png'
        im.save(icon_fullpath)
        return icon_fullpath

    # use RSVG to write PNG file
    if icon.endswith('.svg'):
        img = cairo.ImageSurface(cairo.FORMAT_ARGB32, 64, 64)
        ctx = cairo.Context(img)
        handler = rsvg.Handle(icon)
        handler.render_cairo(ctx)
        icon_fullpath = '/tmp/image.png'
        img.write_to_png(icon_fullpath)
        return icon_fullpath
    return ''

def get_icon_filename(icon):

    # fully qualified path
    icon_fullpath = './tmp/' + icon
    if os.path.exists(icon_fullpath):
        return resize_icon(icon_fullpath)

    # app specified a bare filename without extension
    if icon.find('.png') == -1 and icon.find('.svg') == -1:
        icon = icon + '.png'

    # pixmap
    icon_fullpath = "./tmp/usr/share/pixmaps/%s" % icon
    if os.path.exists(icon_fullpath):
        return resize_icon(icon_fullpath)

    # hicolor, something we don't have to resize
    icon_sizes_no_resize = [ '64x64', '48x48', '32x32' ]
    for s in icon_sizes_no_resize:
        icon_fullpath = './tmp/usr/share/icons/hicolor/' + s + '/apps/' + icon
        if os.path.exists(icon_fullpath):
            return icon_fullpath

    # hicolor, something we have to resize
    icon_sizes_resize = [ '96x96', '128x128', '256x256' ]
    for s in icon_sizes_resize:
        icon_fullpath = './tmp/usr/share/icons/hicolor/' + s + '/apps/' + icon
        if os.path.exists(icon_fullpath):
            return resize_icon(icon_fullpath)

    return ''

class AppstreamBuild:

    def __init__(self):
        #to do something
        self.yb = yum.YumBase()
        self.cat_blacklist = ['GTK', 'Qt', 'KDE']

        # get the list of stock icons
        f = open('./stock-icon-names.txt', 'r')
        self.stock_icons = f.read().rstrip().split('\n')
        f.close()

    def build(self, filename):

        if not os.path.exists('./appstream'):
            os.makedirs('./appstream')
        if not os.path.exists('./icons'):
            os.makedirs('./icons')
        # remove tmp
        if os.path.exists('./tmp'):
            shutil.rmtree('./tmp')
        os.makedirs('./tmp')
        print 'SOURCE\t', filename

        # parse file
        pkg = YumLocalPackage(ts=self.yb.rpmdb.readOnlyTS(), filename=filename)

        # explode contents into tmp, FIXME: use native decompressor
        cmd = "/home/hughsie/Code/app-install/src/app-install-extract-package --package=%s --directory=%s" % (filename, 'tmp')
        p = subprocess.Popen(cmd, cwd='.', shell=True, stdout=subprocess.PIPE)
        p.wait()
        if p.returncode:
            raise StandardError('Cannot extract package: ' + p.stdout)

        # open the AppStream file for writing
        has_header = False
        xml_output_file = './appstream/' + pkg.name + '.xml'
        xml = open(xml_output_file, 'w')

        files = glob.glob("./tmp/usr/share/applications/*.desktop")
        files.sort()
        for f in files:
            config = ConfigParser.RawConfigParser()
            config.read(f)

            # optional
            categories = None
            description = None
            homepage_url = None
            keywords = None
            icon_fullpath = None

            # do not include apps with NoDisplay=True
            try:
                if config.getboolean('Desktop Entry', 'NoDisplay'):
                    print 'IGNORE\t', f, '\t', "not included in the menu"
                    continue
            except Exception, e:
                pass

            # do not include apps with Type != Application
            try:
                if config.get('Desktop Entry', 'Type') != 'Application':
                    print 'IGNORE\t', f, '\t', "not an application"
                    continue;
            except Exception, e:
                continue

            # Do not include apps without a Name
            try:
                name = config.get('Desktop Entry', 'Name')
            except Exception, e:
                print 'IGNORE\t', f, '\t', "no Name"
                continue

            # Do not include apps without a Comment
            try:
                summary = config.get('Desktop Entry', 'Comment')
            except Exception, e:
                print 'IGNORE\t', f, '\t', "no Comment"
                continue
            if len(summary) == 0:
                print 'IGNORE\t', f, '\t', "Comment unspecified"
                continue

            try:
                icon = config.get('Desktop Entry', 'Icon')
            except Exception, e:
                print 'IGNORE\t', f, '\t', "no Icon"
                continue
            if len(icon) == 0:
                print 'IGNORE\t', f, '\t', "Icon unspecified"
                continue

            # Categories are optional but highly reccomended
            try:
                categories = config.get('Desktop Entry', 'Categories')
            except Exception, e:
                pass

            # Keywords are optional but highly reccomended
            try:
                keywords = config.get('Desktop Entry', 'Keywords')
            except Exception, e:
                pass

            # check icon exists
            if icon not in self.stock_icons:
                try:
                    icon_fullpath = get_icon_filename(icon)
                except Exception as e:
                    print 'IGNORE\t', f, '\t', "icon is corrupt:", icon
                    continue
                if not os.path.exists(icon_fullpath):
                    print 'IGNORE\t', f, '\t', "icon does not exist:", icon
                    continue

            print 'PROCESS\t', f

            basename = f.split("/")[-1]
            app_id = basename.replace('.desktop', '')

            # do we have an AppData file?
            appdata_file = './tmp/usr/share/appdata/' + app_id + '.appdata.xml'
            appdata_extra_file = './appdata-extra/' + app_id + '.appdata.xml'
            if os.path.exists(appdata_file) and os.path.exists(appdata_extra_file):
                raise StandardError('both AppData extra and upstream exist: ' + app_id)

            # just use the extra file in places of the missing upstream one
            if os.path.exists(appdata_extra_file):
                appdata_file = appdata_extra_file

            # need to extract details
            if os.path.exists(appdata_file):
                data = fedoraAppstreamData.AppstreamData()
                data.extract(appdata_file)

                # check the id matches
                if data.get_id() != app_id:
                    raise StandardError('The AppData id does not match: ' + app_id)

                # check the licence is okay
                if data.get_licence() != 'CC0':
                    raise StandardError('The AppData licence is not okay: ' + app_id)

                # get optional bits
                homepage_url = data.get_url()
                description = data.get_description()

            # write header
            if not has_header:
                print 'WRITING\t', xml_output_file
                xml.write("<?xml version=\"1.0\"?>\n")
                xml.write("<applications version=\"0.1\">\n")
                has_header = True

            # write content
            xml.write("  <application>\n")
            xml.write("    <id type=\"desktop\">%s</id>\n" % basename)
            xml.write("    <pkgname>%s</pkgname>\n" % pkg.name)
            # FIXME: do translations too
            xml.write("    <name>%s</name>\n" % sanitise_xml(name))
            # FIXME: do translations too
            xml.write("    <summary>%s</summary>\n" % sanitise_xml(summary))
            if icon_fullpath:
                xml.write("    <icon type=\"cached\">%s</icon>\n" % app_id)
            else:
                xml.write("    <icon type=\"stock\">%s</icon>\n" % icon)
            if categories:
                xml.write("    <appcategories>\n")
                categories = categories.split(';')[:-1]
                # check for a common problem
                if 'AudioVideo' in categories:
                    if not 'Audio' in categories and not 'Video' in categories:
                        print 'WARNING\t', f, '\tHas AudioVideo but not Audio or Video'
                        categories.extend(['Audio', 'Video'])
                for cat in categories:
                    if cat in self.cat_blacklist:
                        continue
                    if cat.startswith('X-'):
                        continue
                    xml.write("      <appcategory>%s</appcategory>\n" % cat)
                xml.write("    </appcategories>\n")
            if keywords:
                xml.write("    <keywords>\n")
                for keyword in keywords.split(';')[:-1]:
                    xml.write("      <keyword>%s</keyword>\n" % keyword)
                xml.write("    </keywords>\n")
            if homepage_url:
                xml.write("    <url type=\"homepage\">%s</url>\n" % homepage_url)
            if description:
                xml.write("    <description>%s</description>\n" % description)
            xml.write("  </application>\n")

            # copy icon
            if icon_fullpath:
                output_file = './icons/' + app_id + '.png'
                icon_file = open(icon_fullpath, 'rb')
                icon_data = icon_file.read()
                icon_file.close()
                icon_file = open(output_file, 'wb')
                icon_file.write(icon_data)
                icon_file.close()
                print 'WRITING\t', output_file

        # create AppStream XML
        xml.write("</applications>\n")
        xml.close()
        if not has_header:
            os.remove(xml_output_file)

        # create AppStream icon tar
        if has_header:
            output_file = "./appstream/%s-icons.tar" % pkg.name
            print 'WRITING\t', output_file
            tar = tarfile.open(output_file, "w")
            files = glob.glob("./icons/*.png")
            for f in files:
                tar.add(f, arcname=f.split('/')[-1])
            tar.close()

        # remove tmp
        shutil.rmtree('./tmp')
        shutil.rmtree('./icons')

def main():
    job = AppstreamBuild()
    job.build(sys.argv[1])
    sys.exit(0)

if __name__ == "__main__":
    main()
