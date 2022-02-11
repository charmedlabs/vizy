#
# This file is part of Vizy 
#
# All Vizy source code is provided under the terms of the
# GNU General Public License v2 (http://www.gnu.org/licenses/gpl-2.0.html).
# Those wishing to use Vizy source code, software and/or
# technologies under different licensing terms should contact us at
# support@charmedlabs.com. 
#

import dash_devices
from dash_devices.dependencies import Input, Output
import dash_bootstrap_components as dbc
import dash_html_components as html


class Sidebar:

    def __init__(self, kapp):
        self.kapp = kapp
        self._views = []
        self.view_index = 0
        self.view_set = False
        self.buttons = []

    @property
    def views(self):
        return self._views

    @views.setter
    def views(self, views):
        self._views = views
        inputs = []
        for i, view in enumerate(self._views):
            id_ = str(i) + '-button'
            self.buttons.append(dbc.Row(dbc.Button(view.name, id=id_, active=i==self.view_index, className='side-button'), className='col-sm'))
            inputs.append(Input(id_, 'n_clicks'))
             # create sync callback for each view, but only if we haven't already

        self.kapp.layout = [dbc.Container([ 
            dbc.Row([dbc.Col(html.Div(html.Img(src=self.kapp.get_media_url('vizy.png'))), style={'padding': '0px 0px 0px 0px'} )]),
            dbc.Row([dbc.Col(html.Div(self.buttons, className='button-div'), id='_sidebar', width='auto', style={'background-color': '#e8e8e8', 'padding-right': '0px', 'padding-left': '0px'}),
                dbc.Col([
                    html.Div(dbc.Spinner(id='_wait-spinner', color='#909090', size="md"), id="_wait-spinner-div", style={'display': 'none'}),
                    html.Div(self.view_layout(self.view_index), id='_client-area', style={'padding': '0px', "margin": "0px"})
                ]),
             ])
        ], fluid=True)]

        # Enable first view.
        self._views[self.view_index].view(True)

        # This callback has no output because we need to do things in a certain order.
        # The page should be updated before we enable the view.  
        # The wait spinner should turn off after everything has happened. 
        @self.kapp.callback_shared(None, inputs)
        async def func(*argv):
            context = dash_devices.callback_context
            button_id = context.triggered[-1]['prop_id'].split('.')[0]
            index = int(button_id.split('-')[0])
            return await self.set_view(index)


    async def set_view(self, index):
        if index==self.view_index and self.view_set:
            return
        await self.kapp.push_mods_coro({
            '_wait-spinner-div': {'style': {'display': 'block'}},
            '_client-area': {'style': {'display': 'none'}},
        })
        self._views[self.view_index].view(False)
        self.view_index = index
        await self.activate(self.view_index)

        view_layout = self.view_layout(self.view_index)
        # Set client-area before enabling view.
        await self.kapp.push_mods_coro({
            '_client-area': {
                'children': view_layout
            }
        })
        # Enable view
        self.kapp.loop.run_in_executor(None, self._views[self.view_index].view, True)

        # Flag to indicate that the view has been set.
        self.view_set = True

        return Output('_wait-spinner-div', 'style', {'display': 'none'}), Output('_client-area', 'style', {'display': 'block'})


    # Set the sidebar button as active.  Note, buttons that are clicked are 
    # colored active and we can't make them unactive color.  
    async def activate(self, index):
        active = {}
        for i, button in enumerate(self.buttons):
            active.update({button.children.id: {'active': i==index}})
        await self.kapp.push_mods_coro(active)

    def view_layout(self, index):
        return self.kapp.unwrap(self._views[self.view_index].layout)
