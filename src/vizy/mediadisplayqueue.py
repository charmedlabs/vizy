import os
import kritter
import dash_html_components as html


class MediaDisplayQueue:
    def __init__(self, media_dir, display_width, media_width, media_display_width=300, num_media=25, kapp=None):
        self.display_width = display_width
        self.media_width = media_width
        self.media_display_width = media_display_width
        self.num_media = num_media
        self.kapp = kritter.Kritter.kapp if kapp is None else kapp
        self.set_media_dir(media_dir)
        self.dialog_image = kritter.Kimage(overlay=True)
        self.image_dialog = kritter.Kdialog(title="", layout=[self.dialog_image], size="xl")
        self.dialog_video = kritter.Kvideo(src="")
        self.video_dialog = kritter.Kdialog(title="", layout=[self.dialog_video], size="xl")
        self.layout = html.Div([html.Div(self._create_images(), id=self.kapp.new_id(), style={"white-space": "nowrap", "max-width": f"{self.display_width}px", "width": "100%", "overflow-x": "auto"}), self.image_dialog, self.video_dialog])

    def _create_images(self):
        children = []
        self.images = []
        for i in range(self.num_media):
            kimage = kritter.Kimage(width=self.media_display_width, overlay=True, style={"display": "inline-block", "margin": "5px 5px 5px 0"}, service=None)
            self.images.append(kimage)
            div = html.Div(kimage.layout, id=self.kapp.new_id(), style={"display": "inline-block"})
            
            def func(_kimage):
                def func_():
                    path = _kimage.path
                    mods = []
                    if path.endswith(".mp4"):
                        mods += self.dialog_video.out_src(path)+ self.video_dialog.out_open(True)
                        try:
                            mods += self.video_dialog.out_title(_kimage.data['timestamp']) 
                        except:
                            pass                            
                    else:
                        try:
                            if 'class' in _kimage.data:
                                title = f"{_kimage.data['class']}, {_kimage.data['timestamp']}"
                            else:
                                title = _kimage.data['timestamp']
                        except:
                            title = ""
                        mods += self.dialog_image.out_src(path) + self.image_dialog.out_title(title) + self.image_dialog.out_open(True)
                    return mods
                return func_

            kimage.callback()(func(kimage))
            children.append(div)
        return children

    def get_images_and_data(self):
        images = os.listdir(self.media_dir)
        images = [i for i in images if i.endswith(".jpg") or i.endswith(".mp4")]
        images.sort(reverse=True)

        images_and_data = []
        for image in images:
            data = kritter.load_metadata(os.path.join(self.media_dir, image))
            images_and_data.append((image, data))
            if len(images_and_data)==self.num_media:
                break
        return images_and_data

    def set_media_dir(self, media_dir):
        if media_dir:
            self.media_dir = media_dir
            self.kapp.media_path.insert(0, self.media_dir)

    def out_images(self):
        images_and_data = self.get_images_and_data()
        mods = []
        for i in range(self.num_media):
            if i < len(images_and_data):
                image, data = images_and_data[i]
                self.images[i].path = image
                self.images[i].data = data
                self.images[i].overlay.draw_clear()
                try:
                    video = image.endswith(".mp4")
                    if video:
                        image = data['thumbnail']

                    mods += self.images[i].out_src(image)
                    if 'class' in data:
                        self.images[i].overlay.update_resolution(width=data['width'], height=data['height'])
                        kritter.render_detected(self.images[i].overlay, [data], scale=self.media_display_width/self.media_width)
                    elif video:
                        # create play arrow in overlay
                        ARROW_WIDTH = 0.18
                        ARROW_HEIGHT = ARROW_WIDTH*1.5
                        xoffset0 = (1-ARROW_WIDTH)*data['width']/2
                        xoffset1 = xoffset0 + ARROW_WIDTH*data['width']
                        yoffset0 = (data['height'] - ARROW_HEIGHT*data['width'])/2
                        yoffset1 = yoffset0 + ARROW_HEIGHT*data['width']/2
                        yoffset2 = yoffset1 + ARROW_HEIGHT*data['width']/2
                        points = [(xoffset0, yoffset0), (xoffset0, yoffset2), (xoffset1, yoffset1)]
                        self.images[i].overlay.draw_shape(points, fillcolor="rgba(255,255,255,0.85)", line={"width": 0})
                except:
                    pass
                try:
                    self.images[i].overlay.draw_text(0, data['height']-1, data['timestamp'], fillcolor="black", font=dict(family="sans-serif", size=12, color="white"), xanchor="left", yanchor="bottom")
                except:
                    pass
                mods += self.images[i].overlay.out_draw() + self.images[i].out_disp(True)
            else:
                mods += self.images[i].out_disp(False)
        return mods
